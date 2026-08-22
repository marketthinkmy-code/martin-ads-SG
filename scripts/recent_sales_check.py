"""What has the Paid Student List booked lately? Read-only.

Row-by-row sales from the last 10 days (date · SG marker · campaign · ad · amount), monthly
pace for August vs July, and — the part the operator actually wants to know this week —
whether any recent sale traces back to the campaigns launched or re-opened in the last few
days (Winners Revival, LAL 1-5%, Bread Hooks, Hook Edits, Retarget). Attribution is by the
sheet's own campaign UTM, so a sale only counts for a new campaign if the UTM says so.

Provably-SG uses the account's standing attribution rule (UTM campaign carries the SG
marker). Rows with no parseable date are counted and said so, not silently dropped.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Dict, List, Tuple

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

RECENT_DAYS = 10

# campaigns launched / restructured in the last two weeks, matched on the sheet's campaign UTM
NEW_CAMPAIGNS: List[Tuple[str, str]] = [
    ("Winners Revival", "winnersrevival"),
    ("PURCHASE LAL 1-5%", "purchaselal15"),
    ("Bread Hooks 8月", "breadhooks"),
    ("Hook Edits A/B/C", "hookedits"),
    ("Retarget 30d VV50", "retarget30dvv50"),
]


def sg(campaign_norm: str) -> bool:
    c = campaign_norm or ""
    return ("[sg]" in c) or ("martin-sg" in c) or ("martin sg" in c)


def main() -> None:
    log = get_logger()
    s = load_settings()
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    thursday = today - dt.timedelta(days=(today.weekday() - 3) % 7)
    cutoff = today - dt.timedelta(days=RECENT_DAYS)

    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)

    monthly_all: Dict[str, int] = defaultdict(int)
    monthly_sg: Dict[str, int] = defaultdict(int)
    undated = 0
    recent = []
    for x in sales:
        if x.date is None:
            undated += 1
            continue
        m = x.date.strftime("%Y-%m")
        monthly_all[m] += 1
        if sg(x.campaign):
            monthly_sg[m] += 1
        if x.date >= cutoff:
            recent.append(x)

    log.info("Paid Student List %r: %d rows parsed (%d without a parseable date)",
             s.cpa.sales_tab, len(sales), undated)
    log.info("═" * 100)
    log.info("MONTHLY PACE (all-market / provably-SG)")
    for m in sorted(monthly_all)[-4:]:
        log.info("   %s   %3d / %d", m, monthly_all[m], monthly_sg[m])

    log.info("═" * 100)
    log.info("LAST %d DAYS — every row, newest first", RECENT_DAYS)
    log.info("   %-10s %-3s %-40s %-34s %s", "date", "SG", "campaign (UTM)", "ad (UTM)", "RM")
    wk_all = wk_sg = 0
    for x in sorted(recent, key=lambda r: r.date, reverse=True):
        is_sg = sg(x.campaign)
        if thursday <= x.date <= today:
            wk_all += 1
            wk_sg += is_sg
        log.info("   %-10s %-3s %-40s %-34s %.0f", x.date.isoformat(), "SG" if is_sg else "—",
                 (x.campaign or "∅")[:40], (x.ad or "∅")[:34], x.amount)
    if not recent:
        log.info("   (no sale dated in the last %d days)", RECENT_DAYS)

    log.info("═" * 100)
    log.info("NEW-CAMPAIGN ATTRIBUTION — sales whose campaign UTM points at a campaign from "
             "the last two weeks")
    hits = 0
    for label, key in NEW_CAMPAIGNS:
        rows = [x for x in sales if x.date and x.date >= cutoff
                and key in cpa.ad_key(x.campaign)]
        hits += len(rows)
        marks = "; ".join(f"{x.date} {x.ad[:24]}" for x in rows) if rows else "—"
        log.info("   %-20s %2d   %s", label, len(rows), marks)

    aug = today.strftime("%Y-%m")
    final_summary(
        log, f"Last {RECENT_DAYS} days: {len(recent)} sale(s) on the sheet "
             f"({sum(1 for x in recent if sg(x.campaign))} provably-SG). This ad week "
             f"(Thu {thursday} → today): {wk_all} sale(s), {wk_sg} provably-SG. August so far: "
             f"{monthly_all.get(aug, 0)} all-market / {monthly_sg.get(aug, 0)} SG vs July "
             f"{monthly_all.get('2026-07', 0)}/{monthly_sg.get('2026-07', 0)}. "
             f"{hits} recent sale(s) trace to the newly launched campaigns by campaign UTM. "
             f"Read-only — reporting the sheet as it stands; entry lag means the newest sales "
             f"may not be typed in yet.")


if __name__ == "__main__":
    main()
