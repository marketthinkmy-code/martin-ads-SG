"""誤關 check: every ad name with a sale in the last 14 days vs its switches today. Read-only.

Operator (30 Aug): "我關了很多cpl很高的廣告，你看看 paid student list 那些最近14d 有成交的
廣告，我有沒有誤關？"

So: take every sale on the Paid Student List dated in the last 14 days, resolve it to an ad
NAME KEY (the unit a creative decision is made on — one creative runs as many copies), then
look at every instance of that name in the account TODAY and sort into:

  🔴 誤關嫌疑   — provably-SG sale in the window, and every copy of the name is switched off.
                 Shown with lifetime SG sales, name-key lifetime spend, CPA, and each off
                 copy (campaign · effective status · last-7d spend, to show which were
                 running until recently).
  ✅ 在跑       — provably-SG sale in the window and at least one copy is delivering.
  ⚠️ 非SG成交   — the name sold in the window but no sale carries the SG campaign UTM: on a
                 sheet shared with MY, that is NOT evidence for this account, so it is
                 reported separately, not as 誤關.
  ∅ 對不上     — sold name with no matching ad in this account (organic / renamed / MY-only).

Provably-SG uses the account's standing attribution rule (UTM campaign carries the SG
marker). Nothing is written — the verdicts are recommendations; the switches stay yours.
Entry lag caveat: the newest sales may not be typed into the sheet yet.
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

WINDOW_DAYS = 14


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _sgsale(x) -> bool:  # provably-SG sale — the account's own attribution standard
    return ("[sg]" in x.campaign) or ("martin-sg" in x.campaign) or ("martin sg" in x.campaign)


def main() -> None:
    log = get_logger()
    s = load_settings()
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    d14 = today - dt.timedelta(days=WINDOW_DAYS)
    d7 = today - dt.timedelta(days=7)
    acct = s.meta.account_path
    acc, hard = s.cpa.max_acceptable_myr, s.cpa.hard_stop_myr
    token = result_action_type(s.meta.conversion_event)

    # ── the sheet: sales in the window, by ad name key ──────────────────────────
    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)
    win: Dict[str, List[Any]] = defaultdict(list)      # sales dated in the window, per key
    sglife: Dict[str, int] = defaultdict(int)
    alllife: Dict[str, int] = defaultdict(int)
    for x in sales:
        k = cpa.ad_key(x.ad)
        if not k:
            continue
        alllife[k] += 1
        if _sgsale(x):
            sglife[k] += 1
        if x.date and x.date >= d14:
            win[k].append(x)
    n_win = sum(len(v) for v in win.values())
    n_win_sg = sum(1 for v in win.values() for x in v if _sgsale(x))
    log.info("Paid Student List: %d sale(s) dated %s → %s (%d provably-SG), %d distinct ad names",
             n_win, d14, today, n_win_sg, len(win))

    # ── the account: every instance of every name, switches as of now ───────────
    g = graph_client(s)
    ads: List[Dict[str, Any]] = g._get_all(f"{acct}/ads", {
        "fields": "id,name,status,effective_status,campaign{name}", "limit": 500})
    inst: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for ad in ads:
        inst[cpa.ad_key(ad.get("name") or "")].append(ad)

    life_rows = g.account_insights(acct, level="ad", fields="ad_id,ad_name,spend",
                                   date_preset="maximum")
    life_by_key: Dict[str, float] = defaultdict(float)
    for r in life_rows:
        life_by_key[cpa.ad_key(r.get("ad_name") or "")] += _f(r.get("spend"))
    w14 = {r.get("ad_id"): r for r in g.account_insights(
        acct, level="ad", fields="ad_id,spend,actions",
        time_range={"since": d14.isoformat(), "until": today.isoformat()})}
    w7 = {r.get("ad_id"): r for r in g.account_insights(
        acct, level="ad", fields="ad_id,spend",
        time_range={"since": d7.isoformat(), "until": today.isoformat()})}

    DELIVERING = ("ACTIVE", "IN_PROCESS", "PENDING_REVIEW")
    misclosed, running, nonsg, unmatched = [], [], [], []
    for k, rows in sorted(win.items(), key=lambda kv: -len(kv[1])):
        sg_rows = [x for x in rows if _sgsale(x)]
        copies = inst.get(k) or []
        name = (copies[0].get("name") if copies else rows[0].ad) or k
        live = [a for a in copies if (a.get("effective_status") or "") in DELIVERING]
        rec = {
            "key": k, "name": name, "n": len(rows), "nsg": len(sg_rows),
            "dates": sorted({x.date.isoformat() for x in (sg_rows or rows) if x.date}),
            "sglife": sglife.get(k, 0), "alllife": alllife.get(k, 0),
            "life": life_by_key.get(k, 0.0),
            "cpa": cpa.cpa(life_by_key.get(k, 0.0), sglife.get(k, 0)),
            "copies": copies, "live": live,
        }
        if not copies:
            unmatched.append(rec)
        elif not sg_rows:
            nonsg.append(rec)
        elif live:
            running.append(rec)
        else:
            misclosed.append(rec)

    def cpa_s(v) -> str:
        return "∞" if v == math.inf else f"RM{v:,.0f}"

    log.info("═" * 100)
    log.info("🔴 誤關嫌疑 — SG 有单（14d）但这个名字的每一份 copy 都是关的 (%d)", len(misclosed))
    for r in misclosed:
        hint = ("开回没毛病 (CPA ≤ acceptable)" if r["cpa"] <= acc
                else f"边缘 (CPA ≤ hard stop RM{hard:,.0f})" if r["cpa"] <= hard
                else "有单但历史 CPA 仍超 hard stop — 你自己判")
        log.info("   %s", r["name"])
        log.info("      SG sales 14d=%d (dates %s) · lifetime SG=%d all=%d · spend RM%s · "
                 "CPA %s → %s", r["nsg"], ",".join(r["dates"]), r["sglife"], r["alllife"],
                 f"{r['life']:,.0f}", cpa_s(r["cpa"]), hint)
        for a in r["copies"]:
            sp7 = _f((w7.get(a["id"]) or {}).get("spend"))
            log.info("      · OFF %-14s spent7d RM%-8s %s | %s", a.get("effective_status"),
                     f"{sp7:,.0f}", a["id"], ((a.get("campaign") or {}).get("name") or "")[:46])

    log.info("═" * 100)
    log.info("✅ 有单且在跑 — 不用动 (%d)", len(running))
    for r in running:
        spots = "; ".join(((a.get("campaign") or {}).get("name") or "")[:36] for a in r["live"])
        sp14 = sum(_f((w14.get(a["id"]) or {}).get("spend")) for a in r["live"])
        reg14 = sum(extract_results((w14.get(a["id"]) or {}).get("actions"), token)
                    for a in r["live"])
        cpl = f"RM{sp14 / reg14:,.0f}" if reg14 else "—"
        log.info("   %-44s SG14d=%d · live in: %s · 14d spend RM%s CPL %s",
                 r["name"][:44], r["nsg"], spots, f"{sp14:,.0f}", cpl)

    log.info("═" * 100)
    log.info("⚠️ 名字有单但没有一张是 SG UTM — 多半是 MY 的单，不构成誤關证据 (%d)", len(nonsg))
    for r in nonsg:
        state = "有 copy 在跑" if r["live"] else "全关"
        log.info("   %-44s sales14d=%d (SG 0) · %s", r["name"][:44], r["n"], state)

    log.info("═" * 100)
    log.info("∅ 账户里对不上这个名字 (%d)", len(unmatched))
    for r in unmatched:
        log.info("   %-44s sales14d=%d SG=%d", (r["name"] or "∅")[:44], r["n"], r["nsg"])

    strong = [r for r in misclosed if r["cpa"] <= acc]
    final_summary(
        log, f"{WINDOW_DAYS}d sold names: {len(win)} · 🔴誤關嫌疑 {len(misclosed)} "
             f"(其中 {len(strong)} 个 CPA ≤ acceptable，开回没毛病) · ✅在跑 {len(running)} · "
             f"⚠️非SG成交 {len(nonsg)} · ∅对不上 {len(unmatched)}. Read-only — nothing was "
             f"switched; the sheet's newest sales may lag data entry.")


if __name__ == "__main__":
    main()
