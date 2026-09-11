"""Total daily ad spend right now. Read-only — changes nothing.

Operator (11 Sep): "给我目前 total daily ad spend"

"Daily spend" here = the sum of daily BUDGETS Meta is currently allowed to spend, i.e.
only chains that can actually deliver:

  · ABO ad set counts its daily_budget when the ad set is effective-ACTIVE AND holds at
    least one live ad (ACTIVE; pending-review/in-process count as live-once-approved and
    are flagged).
  · CBO campaign counts its campaign daily_budget ONCE when at least one of its ad sets
    is deliverable.
  · An ACTIVE ad set whose ads are all off delivers nothing — its budget is listed
    separately as 挂着但不花钱, not added to the total.
  · lifetime_budget entities (if any) are reported separately — they have no daily number.

Output: per-campaign breakdown (every counted ad set with its budget + live-ad count),
the not-spending leftovers, and the account total per day. Currency = account currency (MYR).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List

from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

LIVE = {"ACTIVE"}
PENDING = {"PENDING_REVIEW", "IN_PROCESS", "PREAPPROVED"}


def _myr(minor) -> float:
    try:
        return float(minor or 0) / 100.0
    except (TypeError, ValueError):
        return 0.0


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path

    campaigns = g._get_all(f"{acct}/campaigns",
                           {"fields": "id,name,effective_status,daily_budget,lifetime_budget",
                            "limit": 200})
    adsets = g._get_all(f"{acct}/adsets",
                        {"fields": "id,name,campaign_id,effective_status,daily_budget,"
                                   "lifetime_budget", "limit": 500})
    ads = g._get_all(f"{acct}/ads",
                     {"fields": "id,adset_id,effective_status", "limit": 1000})

    live_ads: Dict[str, int] = defaultdict(int)
    pend_ads: Dict[str, int] = defaultdict(int)
    for a in ads:
        st = a.get("effective_status")
        if st in LIVE:
            live_ads[a.get("adset_id")] += 1
        elif st in PENDING:
            pend_ads[a.get("adset_id")] += 1

    sets_by_camp: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for aset in adsets:
        sets_by_camp[aset.get("campaign_id")].append(aset)

    total = 0.0
    idle = 0.0            # ACTIVE chains that cannot deliver (all ads off) — not counted
    idle_lines: List[str] = []
    lifetime_lines: List[str] = []
    n_chains = 0

    log.info("═" * 96)
    log.info("目前每日预算承诺（只算能实际花钱的链条） · account %s · currency %s",
             acct, s.meta.currency)
    log.info("═" * 96)

    for c in sorted(campaigns, key=lambda x: (x.get("name") or "")):
        if c.get("effective_status") != "ACTIVE":
            continue
        cname = c.get("name") or c.get("id")
        cbo = _myr(c.get("daily_budget"))
        rows: List[str] = []
        camp_sum = 0.0
        deliverable = False
        for aset in sorted(sets_by_camp.get(c.get("id"), []), key=lambda x: (x.get("name") or "")):
            if aset.get("effective_status") != "ACTIVE":
                continue
            nl, np_ = live_ads.get(aset.get("id"), 0), pend_ads.get(aset.get("id"), 0)
            ab = _myr(aset.get("daily_budget"))
            if _myr(aset.get("lifetime_budget")) > 0:
                lifetime_lines.append(f"{cname} › {aset.get('name')}  lifetime "
                                      f"RM{_myr(aset.get('lifetime_budget')):,.0f}")
            tag = f"{nl} live ad" + ("s" if nl != 1 else "") + (f" +{np_} in review" if np_ else "")
            if nl + np_ == 0:
                if ab > 0 and not cbo:
                    idle += ab
                    idle_lines.append(f"{cname} › {aset.get('name')}  RM{ab:,.0f}/day · 0 live ads")
                continue
            deliverable = True
            if cbo:
                rows.append(f"      · {aset.get('name')}  ({tag}) — 用 campaign 预算")
            else:
                camp_sum += ab
                n_chains += 1
                rows.append(f"      · {aset.get('name')}  RM{ab:,.0f}/day  ({tag})")
        if not deliverable:
            if cbo:
                idle += cbo
                idle_lines.append(f"{cname}  [CBO RM{cbo:,.0f}/day] · 无可投放 ad set")
            continue
        if cbo:
            camp_sum = cbo
            n_chains += 1
            log.info("▸ %s   [CBO] RM%s/day", cname, f"{cbo:,.0f}")
        else:
            log.info("▸ %s   RM%s/day", cname, f"{camp_sum:,.0f}")
        for r in rows:
            log.info("%s", r)
        total += camp_sum

    log.info("═" * 96)
    if idle_lines:
        log.info("挂着但不花钱（ACTIVE 但没有一条 live ad，预算不计入 total）:")
        for r in idle_lines:
            log.info("      %s", r)
        log.info("      小计（若把广告开回来会多花的）: RM%s/day", f"{idle:,.0f}")
    if lifetime_lines:
        log.info("lifetime 预算实体（无每日数，单列）:")
        for r in lifetime_lines:
            log.info("      %s", r)
    log.info("═" * 96)
    log.info("TOTAL DAILY AD SPEND（当前可投放链条的每日预算合计）: RM%s /day  ·  %d 条预算链",
             f"{total:,.0f}", n_chains)
    final_summary(log, f"Total daily budget of deliverable chains: RM{total:,.2f}/day "
                       f"across {n_chains} budget chain(s); idle-but-ACTIVE RM{idle:,.2f}/day "
                       f"not counted. Read-only run.")


if __name__ == "__main__":
    main()
