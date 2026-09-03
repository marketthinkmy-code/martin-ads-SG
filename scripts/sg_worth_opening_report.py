"""SG worth-opening report: every ad name that ever sold, ranked by money. Read-only.

Operator (3 Sep): "統計給我知道，SG 新加坡 的 什麼 ad 值得我開？"

The unit is the ad NAME KEY (one creative runs as many copies; the sheet attributes sales by
name). For every name with at least one provably-SG sale (UTM campaign carries the SG marker
— the account's own attribution standard):

    lifetime SG sales · sales in the last 30d · lifetime name-key spend (Meta insights,
    maximum window) · lifetime CPA · last SG sale date · copies in the account and whether
    any is delivering right now.

Buckets, judged on the account's own thresholds (target RM740 / acceptable RM1,040 /
hard stop RM1,300):

  🟢 值得开   — no copy delivering, CPA ≤ acceptable (≤ target flagged 强).
  🟡 边缘     — off, CPA in the acceptable→hard-stop band: the operator's call.
  ✅ 在跑     — already delivering somewhere (nothing to open, listed for context).
  ⚪ 不值得   — off with CPA above the hard stop (summed, not itemised).
  ∅ 对不上   — sold names with no matching ad in this account (can't be opened here).

Honesty tags: 薄 = thin data (under RM1,000 spend or a single sale — a great CPA on thin
data is a bet, not proof); 🕐 = stale (no SG sale in 90+ days — the market may have moved).
Nothing is switched; entry lag means the newest sales may not be typed in yet.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Any, Dict, List

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

DELIVERING = ("ACTIVE", "IN_PROCESS", "PENDING_REVIEW")


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _sgsale(x) -> bool:
    return ("[sg]" in x.campaign) or ("martin-sg" in x.campaign) or ("martin sg" in x.campaign)


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    d30, d90 = today - dt.timedelta(days=30), today - dt.timedelta(days=90)
    tgt, acc, hard = s.cpa.target_myr, s.cpa.max_acceptable_myr, s.cpa.hard_stop_myr
    min_spend = s.cpa.min_spend_myr

    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)
    sglife: Dict[str, int] = defaultdict(int)
    sg30: Dict[str, int] = defaultdict(int)
    last_sale: Dict[str, dt.date] = {}
    display: Dict[str, str] = {}
    for x in sales:
        k = cpa.ad_key(x.ad)
        if not k or not _sgsale(x):
            continue
        sglife[k] += 1
        display.setdefault(k, x.ad)
        if x.date:
            if x.date >= d30:
                sg30[k] += 1
            if k not in last_sale or x.date > last_sale[k]:
                last_sale[k] = x.date

    life_rows = g.account_insights(acct, level="ad", fields="ad_id,ad_name,spend",
                                   date_preset="maximum")
    life_by_key: Dict[str, float] = defaultdict(float)
    for r in life_rows:
        life_by_key[cpa.ad_key(r.get("ad_name") or "")] += _f(r.get("spend"))

    ads = g._get_all(f"{acct}/ads", {"fields": "id,name,effective_status", "limit": 500})
    inst: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for a in ads:
        inst[cpa.ad_key(a.get("name") or "")].append(a)

    rows = []
    for k, n in sglife.items():
        copies = inst.get(k) or []
        live = any((a.get("effective_status") or "") in DELIVERING for a in copies)
        spend = life_by_key.get(k, 0.0)
        c = spend / n if spend > 0 else None
        name = max((a.get("name") for a in copies), key=lambda v: len(v or ""), default=display[k])
        rows.append({"k": k, "name": name or display[k], "n": n, "n30": sg30.get(k, 0),
                     "spend": spend, "cpa": c, "last": last_sale.get(k),
                     "copies": len(copies), "live": live,
                     "thin": spend < min_spend or n < 2,
                     "stale": (last_sale.get(k) or d90) < d90})

    def line(r) -> str:
        tags = ("薄" if r["thin"] else "") + ("🕐" if r["stale"] else "")
        cpa_s = f"RM{r['cpa']:,.0f}" if r["cpa"] else "无spend记录"
        return (f"{cpa_s:>10}  SG {r['n']:>2}单(30d:{r['n30']})  spend RM{r['spend']:>9,.0f}  "
                f"last {r['last'] or '—'}  copies {r['copies']:>2}  {tags:<3} {r['name'][:46]}")

    openable = [r for r in rows if not r["live"] and r["copies"] and r["cpa"]]
    strong = sorted([r for r in openable if r["cpa"] <= tgt], key=lambda r: r["cpa"])
    good = sorted([r for r in openable if tgt < r["cpa"] <= acc], key=lambda r: r["cpa"])
    edge = sorted([r for r in openable if acc < r["cpa"] <= hard], key=lambda r: r["cpa"])
    bad = [r for r in openable if r["cpa"] > hard]
    running = sorted([r for r in rows if r["live"]], key=lambda r: r["cpa"] or 9e9)
    unmatched = [r for r in rows if not r["copies"]]
    nospend = [r for r in rows if r["copies"] and not r["live"] and not r["cpa"]]

    log.info("Provably-SG sold names: %d · thresholds target RM%.0f / acceptable RM%.0f / "
             "hard RM%.0f · 薄=spend<RM%.0f or <2 sales · 🕐=no SG sale 90d+",
             len(rows), tgt, acc, hard, min_spend)
    log.info("═" * 110)
    log.info("🟢 强 — 关着 + CPA ≤ target RM%.0f (%d)", tgt, len(strong))
    for r in strong:
        log.info("   %s", line(r))
    log.info("═" * 110)
    log.info("🟢 值得开 — 关着 + CPA ≤ acceptable RM%.0f (%d)", acc, len(good))
    for r in good:
        log.info("   %s", line(r))
    log.info("═" * 110)
    log.info("🟡 边缘 — 关着 + CPA 在 acceptable→hard stop (%d)", len(edge))
    for r in edge:
        log.info("   %s", line(r))
    log.info("═" * 110)
    log.info("✅ 已经在跑 (%d)", len(running))
    for r in running:
        log.info("   %s", line(r))
    log.info("═" * 110)
    log.info("⚪ 关着但 CPA > hard stop — 不值得，共 %d 个（spend 合计 RM%,.0f）",
             len(bad), sum(r["spend"] for r in bad))
    for r in sorted(bad, key=lambda r: -r["spend"])[:5]:
        log.info("   %s", line(r))
    if nospend:
        log.info("═" * 110)
        log.info("❓ 有 SG 单但查不到 spend（名字对得上但 insights 无记录）(%d)", len(nospend))
        for r in nospend:
            log.info("   %s", line(r))
    if unmatched:
        log.info("═" * 110)
        log.info("∅ 账户里没有这个名字（organic / 改名 / 别的账户）(%d)", len(unmatched))
        for r in unmatched:
            log.info("   %-40s SG %d单 last %s", r["name"][:40], r["n"], r["last"] or "—")

    final_summary(
        log, f"{len(rows)} sold names · 🟢strong {len(strong)} + 🟢good {len(good)} openable "
             f"now, 🟡edge {len(edge)}, ✅running {len(running)}, ⚪not-worth {len(bad)}, "
             f"∅unmatched {len(unmatched)}. Read-only — nothing switched; sheet entry lag "
             f"applies. Thin-data (薄) winners are bets, not proof: fund small first.")


if __name__ == "__main__":
    main()
