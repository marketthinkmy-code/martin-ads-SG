"""Keep-or-pause verdict for high-CPL ads — this week's CPL vs real paid sales / CPA (read-only).

For every ACTIVE registration-optimized ad, over the week-to-date window (most recent Thursday
→ today, matching the operator's weekly ON/reset), it assembles:
  · spend + registrations + CPL          (Meta insights, this week)
  · real PAID sales this week + last 30d  (Paid Student List, ad-name keyed; SG-attributed + all)
  · CPA = spend ÷ paid sales              (this week, and 30d for a lag-fair read)
then gives a verdict for the over-CPL ones, per the operator's CPA-rescue policy:
  🟢 KEEP      — over CPL but real sales at CPA ≤ acceptable (registration cost alone never kills
                 a money-making ad)
  🟡 WATCH     — over CPL, sales but CPA in the 1040–1300 band, or thin data
  🕐 TOO-NEW   — over CPL, no sales yet but younger than the conversion window (sales still lag)
  🔴 PAUSE     — over CPL, zero paid sales after real spend and past the conversion window
Writes nothing.
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _s(v) -> str:
    return "—" if v is None else ("∞" if v == math.inf else f"{v:.0f}")


def _sgsale(x) -> bool:  # provably-SG sale (UTM campaign carries the SG prefix)
    return ("[sg]" in x.campaign) or ("martin-sg" in x.campaign) or ("martin sg" in x.campaign)


def main() -> None:
    s = load_settings()
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    thursday = today - dt.timedelta(days=(today.weekday() - 3) % 7)  # Mon=0..Thu=3..Sun=6
    d30 = today - dt.timedelta(days=30)
    acct = s.meta.account_path
    ceil = s.kpi.cpl_threshold_myr
    tgt, healthy, acc, hard = s.cpa.target_myr, s.cpa.healthy_max_myr, s.cpa.max_acceptable_myr, s.cpa.hard_stop_myr
    conv_days, min_spend = s.cpa.conversion_days, s.cpa.min_spend_myr
    token = result_action_type(s.meta.conversion_event)
    want = (s.meta.conversion_event or "").upper()

    # ── paid sales by ad NAME: this week + last 30d, SG-attributed + all-market ──
    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)
    wk_sg, wk_all, m30_sg, m30_all = defaultdict(int), defaultdict(int), defaultdict(int), defaultdict(int)
    for x in sales:
        k = cpa.ad_key(x.ad)
        if not k or not x.date:
            continue
        sg = _sgsale(x)
        if thursday <= x.date <= today:
            wk_all[k] += 1
            wk_sg[k] += sg
        if x.date > d30:
            m30_all[k] += 1
            m30_sg[k] += sg

    g = graph_client(s)
    wk = {r.get("ad_id"): r for r in g.account_insights(
        acct, level="ad", fields="ad_id,spend,actions",
        time_range={"since": thursday.isoformat(), "until": today.isoformat()})}
    sp30 = {r.get("ad_id"): _f(r.get("spend")) for r in g.account_insights(
        acct, level="ad", fields="ad_id,spend", time_range={"since": d30.isoformat(), "until": today.isoformat()})}

    ads = g._get_all(f"{acct}/ads", {
        "fields": "id,name,created_time,effective_status,adset{name,promoted_object}", "limit": 500})

    rows = []
    for ad in ads:
        if ad.get("effective_status") != "ACTIVE":
            continue
        adset = ad.get("adset") or {}
        if ((adset.get("promoted_object") or {}).get("custom_event_type") or "").upper() != want:
            continue
        aid, name = ad["id"], ad.get("name", ad["id"])
        w = wk.get(aid) or {}
        spw, regw = _f(w.get("spend")), extract_results(w.get("actions"), token)
        if spw <= 0:
            continue  # no spend this week → not in the "keep opening?" question
        cplw = (spw / regw) if regw > 0 else (math.inf if spw > 0 else None)
        k = cpa.ad_key(name)
        nwsg, nw = wk_sg.get(k, 0), wk_all.get(k, 0)
        n30sg, n30 = m30_sg.get(k, 0), m30_all.get(k, 0)
        cpaw = cpa.cpa(spw, nwsg)
        cpa30 = cpa.cpa(sp30.get(aid, 0.0), n30sg)
        created = cpa.parse_date((ad.get("created_time") or "")[:10])
        age = (today - created).days if created else None

        # ── verdict ──
        if cplw is not None and cplw != math.inf and cplw <= ceil:
            v = "✅ CPL ok"
        elif n30sg >= 1 and cpa30 is not None and cpa30 != math.inf and cpa30 <= acc:
            v = f"🟢 KEEP (SG sale · CPA {_s(cpa30)})"
        elif n30sg >= 1 and cpa30 is not None and cpa30 != math.inf and cpa30 <= hard:
            v = f"🟡 WATCH (CPA {_s(cpa30)} high)"
        elif n30sg == 0 and n30 >= 2:
            v = f"🟡 WATCH (name sold {n30}× but 0 SG — attribution?)"
        elif age is not None and age < conv_days:
            v = f"🕐 TOO-NEW ({age}d — sales lag)"
        elif sp30.get(aid, 0.0) >= min_spend and n30 == 0:
            v = "🔴 PAUSE (0 sales · matured)"
        else:
            v = "🟡 WATCH (thin)"
        rows.append({"name": name, "adset": adset.get("name", "∅"), "spw": spw, "regw": regw,
                     "cplw": cplw, "nwsg": nwsg, "nw": nw, "n30sg": n30sg, "n30": n30,
                     "sp30": sp30.get(aid, 0.0), "cpa30": cpa30, "age": age, "v": v})

    print(f"KEEP-OR-PAUSE — SG · week-to-date {thursday}→{today}  ·  CPL ceiling RM{ceil:.0f} · "
          f"CPA acc RM{acc:.0f}/hard RM{hard:.0f} · conv window {conv_days}d\n")
    print(f"Active reg-optimized ads with spend this week: {len(rows)}   "
          f"(paid sales: SG = provably-SG only; name = MY+SG shared-name)\n")
    hdr = (f"{'verdict':30}|{'ad name':30}|{'wk sp/reg/CPL':>16}|{'wk sale SG/name':>15}|"
           f"{'30d sale SG/name':>16}|{'30d sp→CPA':>14}|age")
    print(hdr); print("-" * len(hdr))
    order = {"🔴": 0, "🕐": 1, "🟡": 2, "🟢": 3, "✅": 4}
    for r in sorted(rows, key=lambda r: (order.get(r["v"][0], 9), -(r["cplw"] if r["cplw"] not in (None, math.inf) else 1e9))):
        c = f"{r['spw']:.0f}/{r['regw']:.0f}/{_s(r['cplw'])}"
        c2 = f"{r['nwsg']}/{r['nw']}"
        c3 = f"{r['n30sg']}/{r['n30']}"
        c4 = f"{r['sp30']:.0f}→{_s(r['cpa30'])}"
        print(f"{r['v']:30}|{r['name'][:30]:30}|{c:>16}|{c2:>15}|{c3:>16}|{c4:>14}|{r['age']}")


if __name__ == "__main__":
    main()
