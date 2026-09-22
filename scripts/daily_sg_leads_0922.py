"""SG daily leads vs the operator's tracking sheet (read-only).

Operator (22 Sep): SG landing-page registers stuck at exactly 4/day for 9/18-9/21 while
spend varied — 异常. Pull Meta's own per-day numbers for the SG account (9/16 → today):
account-level spend + conversion-event leads per day, then per-ad leads per day, so we
can see whether Meta agrees with the sheet's 4/4/4/4 (delivery-side real) or disagrees
(landing-page tracking / data-entry side problem).
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Dict

from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

SINCE = dt.date(2026, 9, 16)


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    token = result_action_type(s.meta.conversion_event)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()

    log.info("conversion event token being counted: %r", token)
    rows = g._get_all(f"{acct}/insights", {
        "level": "account", "fields": "spend,actions", "time_increment": 1,
        "time_range": f'{{"since":"{SINCE}","until":"{today}"}}', "limit": 100})
    log.info("═" * 88)
    log.info("① SG 账户逐日（Meta 口径）")
    log.info("═" * 88)
    for r in rows:
        d = r.get("date_start")
        sp = float(r.get("spend") or 0)
        ld = extract_results(r.get("actions"), token)
        cpl = f"RM{sp / ld:,.0f}" if ld else "—"
        log.info("  %s  花 RM%-8.2f leads %-3d CPL %s", d, sp, int(ld), cpl)

    ad_rows = g._get_all(f"{acct}/insights", {
        "level": "ad", "fields": "ad_name,spend,actions", "time_increment": 1,
        "time_range": f'{{"since":"{SINCE}","until":"{today}"}}', "limit": 500})
    per_day: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for r in ad_rows:
        ld = extract_results(r.get("actions"), token)
        if ld:
            per_day[r.get("date_start")][(r.get("ad_name") or "?")[:40]] += ld
    log.info("═" * 88)
    log.info("② 逐日 · 哪支广告出的 lead")
    log.info("═" * 88)
    for d in sorted(per_day):
        parts = " · ".join(f"{n}×{int(v)}" for n, v in sorted(per_day[d].items(),
                                                              key=lambda kv: -kv[1]))
        log.info("  %s  %s", d, parts)

    final_summary(log, "Daily SG breakdown printed — compare with the sheet's "
                       "4/4/4/4 register column. Read-only.")


if __name__ == "__main__":
    main()
