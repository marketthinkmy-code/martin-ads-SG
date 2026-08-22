"""Thursday→today, both directions: which paused ads deserve reopening, which live ads deserve
closing. Read-only.

THE OPERATOR'S FEAR, PRECISELY
------------------------------
Since Thursday a lot of ads were switched off — some by the CPL guardrail, some by hand. The CPL
guardrail judges registrations only, so it kills exactly the ads the operator is worried about:
CPL above the RM65 ceiling but a CPA that says the ad MAKES MONEY. Registration cost alone must
never kill a money-making ad (the CPL_RESCUED policy in adbot.cpa) — but the guardrail cannot see
sales, so this audit re-judges every switched-off ad on money.

And the mirror image: ads still running whose registrations look fine but that have never
produced a provably-SG paid student, or whose CPA sits above the hard stop.

HOW ADS ARE JUDGED
------------------
Sales are provably-SG only (UTM campaign carries the SG marker — the account's own attribution
standard). Economics are computed per ad NAME KEY, because the sheet attributes sales by name and
one creative often runs as several copies: a copy's worthiness comes from its creative's record,
not from which duplicate happened to carry the spend.

  PAUSED side (in some paused state, spent money in the last 7 days — i.e. switched off recently):
    🟢 REOPEN   — creative has provably-SG sales at lifetime CPA ≤ acceptable (RM1,040); ≤ target
                  (RM740) is flagged as strong. This is the "CPL high, CPA low" ad by definition.
    🟡 REVIEW   — sales but CPA in the acceptable→hard-stop band, or the name sells in MY but has
                  no SG sale (works, but not proven HERE).
    🕐 TOO-NEW  — younger than the conversion window; sales lag registrations, judging it now is
                  premature in either direction.
    ⚪ STAY OFF — zero SG sales after real spend, or CPA above the hard stop. The pause was right.

  ACTIVE side (spent money since Thursday):
    🔴 CLOSE    — proven CPA above the RM1,300 hard stop, or matured + well-funded with zero
                  sales anywhere.
    🟢 KEEP     — over the CPL ceiling but CPA ≤ acceptable: the rescue case, do NOT let the
                  guardrail take it.
    ✅ / 🟡 / 🕐 — CPL fine / thin data / too new.

Nothing is written. The reopen/close lists at the end are recommendations for the operator.
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from typing import Any, Dict, List

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _s(v) -> str:
    return "—" if v is None else ("∞" if v == math.inf else f"{v:,.0f}")


def _sgsale(x) -> bool:  # provably-SG sale — the account's own attribution standard
    return ("[sg]" in x.campaign) or ("martin-sg" in x.campaign) or ("martin sg" in x.campaign)


def main() -> None:
    log = get_logger()
    s = load_settings()
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    thursday = today - dt.timedelta(days=(today.weekday() - 3) % 7)
    d7 = today - dt.timedelta(days=7)
    d30 = today - dt.timedelta(days=30)
    acct = s.meta.account_path
    ceil = s.kpi.cpl_threshold_myr
    tgt, acc, hard = s.cpa.target_myr, s.cpa.max_acceptable_myr, s.cpa.hard_stop_myr
    conv_days, min_spend = s.cpa.conversion_days, s.cpa.min_spend_myr
    token = result_action_type(s.meta.conversion_event)
    want = (s.meta.conversion_event or "").upper()

    # ── sales by ad NAME key: 30d + lifetime, SG lane + all-market context ──────
    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)
    sg30, sglife, alllife = defaultdict(int), defaultdict(int), defaultdict(int)
    for x in sales:
        k = cpa.ad_key(x.ad)
        if not k:
            continue
        sg = _sgsale(x)
        alllife[k] += 1
        if sg:
            sglife[k] += 1
            if x.date and x.date > d30:
                sg30[k] += 1

    # ── spend: this week, last 7d, last 30d, lifetime — one insights call each ──
    g = graph_client(s)

    def by_ad(rows):
        return {r.get("ad_id"): r for r in rows}

    wk = by_ad(g.account_insights(acct, level="ad", fields="ad_id,ad_name,spend,actions",
                                  time_range={"since": thursday.isoformat(),
                                              "until": today.isoformat()}))
    w7 = by_ad(g.account_insights(acct, level="ad", fields="ad_id,spend",
                                  time_range={"since": d7.isoformat(), "until": today.isoformat()}))
    life_rows = g.account_insights(acct, level="ad", fields="ad_id,ad_name,spend",
                                   date_preset="maximum")
    sp30_rows = g.account_insights(acct, level="ad", fields="ad_id,ad_name,spend",
                                   time_range={"since": d30.isoformat(),
                                               "until": today.isoformat()})
    # name-key economics: the unit a creative decision is made on
    life_by_key, sp30_by_key = defaultdict(float), defaultdict(float)
    for r in life_rows:
        life_by_key[cpa.ad_key(r.get("ad_name") or "")] += _f(r.get("spend"))
    for r in sp30_rows:
        sp30_by_key[cpa.ad_key(r.get("ad_name") or "")] += _f(r.get("spend"))

    ads: List[Dict[str, Any]] = g._get_all(f"{acct}/ads", {
        "fields": "id,name,status,effective_status,created_time,"
                  "adset{name,promoted_object},campaign{name}", "limit": 500})

    reopen, review, stay, close, keep, ok_rows = [], [], [], [], [], []
    for ad in ads:
        adset = ad.get("adset") or {}
        if ((adset.get("promoted_object") or {}).get("custom_event_type") or "").upper() != want:
            continue
        aid, name = ad["id"], ad.get("name", ad["id"])
        eff = ad.get("effective_status") or "?"
        k = cpa.ad_key(name)
        spw = _f((wk.get(aid) or {}).get("spend"))
        sp7 = _f((w7.get(aid) or {}).get("spend"))
        regw = extract_results((wk.get(aid) or {}).get("actions"), token)
        cplw = (spw / regw) if regw > 0 else (math.inf if spw > 0 else None)
        nsg, nsg30, nall = sglife.get(k, 0), sg30.get(k, 0), alllife.get(k, 0)
        cpa_life = cpa.cpa(life_by_key.get(k, 0.0), nsg)
        created = cpa.parse_date((ad.get("created_time") or "")[:10])
        age = (today - created).days if created else None
        row = {"id": aid, "name": name, "camp": (ad.get("campaign") or {}).get("name", "")[:34],
               "eff": eff, "spw": spw, "regw": regw, "cplw": cplw, "nsg": nsg, "nsg30": nsg30,
               "nall": nall, "cpa": cpa_life, "life": life_by_key.get(k, 0.0), "age": age}

        if eff == "ACTIVE":
            if spw <= 0:
                continue
            if nsg >= 1 and cpa_life != math.inf and cpa_life > hard \
                    and life_by_key.get(k, 0.0) >= min_spend:
                close.append(row)
            elif cplw is not None and cplw != math.inf and cplw <= ceil:
                ok_rows.append(row)
            elif nsg >= 1 and cpa_life != math.inf and cpa_life <= acc:
                keep.append(row)          # over CPL, but the creative makes money — the rescue
            elif age is not None and age < conv_days:
                ok_rows.append({**row, "toonew": True})
            elif nsg == 0 and nall == 0 and life_by_key.get(k, 0.0) >= min_spend:
                close.append(row)         # matured, funded, never sold anywhere
            else:
                review.append({**row, "side": "active"})
        else:
            # switched off — only interesting if it was actually running recently
            if sp7 <= 0:
                continue
            if age is not None and age < conv_days and nsg == 0:
                review.append({**row, "side": "paused-toonew"})
            elif nsg >= 1 and cpa_life != math.inf and cpa_life <= acc:
                reopen.append(row)        # CPL high, CPA low — wrongly killed
            elif nsg >= 1 and cpa_life != math.inf and cpa_life <= hard:
                review.append({**row, "side": "paused"})
            elif nsg == 0 and nall >= 2:
                review.append({**row, "side": "paused-my"})
            else:
                stay.append(row)

    def show(rows, label):
        log.info("═" * 100)
        log.info(label)
        if not rows:
            log.info("   (none)")
            return
        log.info("   %-34s %-16s %13s %9s %9s %11s", "ad", "status", "wk sp/reg/CPL",
                 "SG 30d/∑", "life sp", "SG CPA")
        for r in sorted(rows, key=lambda r: -(r["spw"] or 0)):
            log.info("   %-34s %-16s %5.0f/%2.0f/%-5s %4d/%-4d %9.0f %11s   %s",
                     r["name"][:34], r["eff"], r["spw"], r["regw"], _s(r["cplw"]),
                     r["nsg30"], r["nsg"], r["life"], _s(r["cpa"]), r["camp"])

    show(reopen, f"🟢 REOPEN — switched off, but the creative has provably-SG sales at CPA ≤ "
                 f"RM{acc:,.0f} (CPL high · CPA low = the ads the operator is afraid were killed)")
    show(close, f"🔴 CLOSE — still running with CPA above RM{hard:,.0f} (proven, funded) or "
                f"matured + ≥RM{min_spend:,.0f} lifetime and zero sales anywhere")
    show(keep, f"🟢 KEEP RUNNING (rescued) — over the RM{ceil:,.0f} CPL ceiling this week but "
               f"CPA ≤ RM{acc:,.0f}: do NOT let the CPL guardrail take these")
    show([r for r in review], "🟡 REVIEW — borderline (CPA in the grey band, MY-only sellers, "
                              "or too new to judge)")
    show(stay, "⚪ STAY OFF — the pause was right (no SG sales after real spend, or CPA above "
               "the hard stop)")
    show(ok_rows, "✅ FINE — running with CPL inside the ceiling (or too new, still in the "
                  "conversion window)")

    strong = [r for r in reopen if r["cpa"] is not None and r["cpa"] != math.inf and r["cpa"] <= tgt]
    final_summary(
        log, f"Week {thursday}→{today}: {len(reopen)} switched-off ad(s) deserve REOPENING — "
             f"real provably-SG sales at CPA ≤ RM{acc:,.0f}"
             + (f", {len(strong)} of them under the RM{tgt:,.0f} target" if strong else "")
             + f" — and {len(close)} running ad(s) deserve CLOSING. {len(keep)} over-CPL ad(s) "
               f"are rescued by their CPA and must stay on. {len(review)} borderline for the "
               f"operator's own call, {len(stay)} pauses were right, {len(ok_rows)} running fine. "
               f"Read-only: nothing was changed.")


if __name__ == "__main__":
    main()
