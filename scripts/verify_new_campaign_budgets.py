"""Read back what the two new campaigns will actually SPEND per day — no writes.

WHY THIS EXISTS
---------------
The 1-5-3 build sent daily_budget = 3000 minor units (RM30) on each of the five band ad sets and
reported RM150/day total. A later read of those ad sets returned MYR100.00 each. Either the read
is formatting something else, or Meta raised every band to its enforced minimum and the campaign
actually costs RM500/day — 3.3x what was reported, on a campaign that is one click from live.

A budget figure that might be wrong by 3x is not something to hand over with a caveat, so this
resolves it against the raw API rather than a formatted view: the raw minor-unit values on every
ad set and campaign, plus the account's own published minimums, which say whether RM30 was ever
a legal budget for a conversion-optimised ad set in this account.

Read-only. Nothing here changes an entity.
"""
from __future__ import annotations

from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

CAMPAIGNS = [
    ("PURCHASE LAL 1-5% | 1-5-3", "120257761432150093"),
    ("Retarget 30d VV50 | 1-1-1", "120257762100210093"),
]

ACCT_FIELDS = "name,currency,min_daily_budget,min_campaign_group_spend_cap"


def minimums(g, acct_path: str, log) -> dict:
    """Per-optimisation-class floors. They live on the minimum_budgets EDGE — asking the account
    node for min_daily_budget_high_freq returns "(#100) Tried accessing nonexisting field".

    low_freq is the one that binds a conversion-optimised ad set: a purchase or a lead is a rare
    event, so Meta demands a bigger daily budget than it does for clicks. This is a nice-to-have
    for explaining a number, never a reason to lose the number itself, so a failure here is
    logged and stepped over.
    """
    try:
        rows = g._request("GET", f"{acct_path}/minimum_budgets").get("data") or []
        return rows[0] if rows else {}
    except Exception as exc:                                       # noqa: BLE001
        log.warning("   (could not read minimum_budgets: %s)", exc)
        return {}


def money(v, cur: str) -> str:
    """Minor units -> a figure that can be compared against what was sent."""
    if v in (None, ""):
        return "—"
    return f"{cur} {int(v) / 100:,.2f}  (raw {v})"


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)

    acct = g._request("GET", s.meta.account_path, params={"fields": ACCT_FIELDS})
    cur = acct.get("currency", "MYR")
    mins = minimums(g, s.meta.account_path, log)
    log.info("account %s (%s) · %s", acct.get("name"), s.meta.account_path, cur)
    log.info("   min daily budget · high-freq (clicks/impressions): %s",
             money(mins.get("min_daily_budget_high_freq"), cur))
    log.info("   min daily budget · LOW-freq  (conversions)       : %s",
             money(mins.get("min_daily_budget_low_freq"), cur))

    grand = 0
    notes = []
    for label, cid in CAMPAIGNS:
        log.info("═" * 88)
        c = g._request("GET", cid, params={
            "fields": "name,status,daily_budget,lifetime_budget,bid_strategy,"
                      "is_adset_budget_sharing_enabled"})
        log.info("── %s  %s", label, cid)
        log.info("   status=%s · campaign daily=%s", c.get("status"),
                 money(c.get("daily_budget"), cur))

        sets = g._request("GET", f"{cid}/adsets", params={
            "fields": "name,status,daily_budget,lifetime_budget,optimization_goal,bid_strategy",
            "limit": 50}).get("data", [])
        sub = 0
        for a in sets:
            d = a.get("daily_budget")
            sub += int(d) if d else 0
            log.info("      %-42s %-8s %s  [%s]", a.get("name", "")[:42], a.get("status"),
                     money(d, cur), a.get("optimization_goal"))
        camp_daily = int(c["daily_budget"]) if c.get("daily_budget") else 0
        spend = camp_daily or sub
        grand += spend
        log.info("   → this campaign spends %s/day when activated", money(spend, cur))
        if sub and camp_daily:
            notes.append(f"{label} has BOTH a campaign budget and ad set budgets")

    log.info("═" * 88)
    log.info("BOTH campaigns together: %s/day once activated", money(grand, cur))

    low = mins.get("min_daily_budget_low_freq")
    verdict = ""
    if low:
        verdict = (f" The account's minimum for a conversion-optimised ad set is "
                   f"{money(low, cur).split('(')[0].strip()}/day, so any band budget below that "
                   f"was never legal and Meta raised it.")
    final_summary(
        log, f"Both new campaigns together will spend {money(grand, cur).split('(')[0].strip()}"
             f"/day the moment they are activated.{verdict} Figures are the raw stored minor-unit "
             f"values, not what the build sent.{' ' + '; '.join(notes) if notes else ''}")


if __name__ == "__main__":
    main()
