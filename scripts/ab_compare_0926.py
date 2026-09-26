"""A/B 第一份对比 (read-only, 26 Sep 晚): 老账户 vs 新账户, 9/25 → 今天.

Scheduled readout (trigger "A/B 第一份对比"): the operator moved the SG board to
act_1179668409969241 on 9/25 evening to test whether the old ad account itself was
the problem. Compare, per day per account: spend · link clicks · CPC · leads · CPL ·
click→lead rate (old-account baseline before the move: CPC 7.2-7.7 · CPL 100+ ·
click→lead 0-3.6%). New-account extras: today's per-adset breakdown, spend-cap fields
(new accounts often carry an initial daily spend limit), ad review/restriction states
(disapproved / with issues / still in review), and every campaign's on/off + budget
(shows whether Sep 1-1-2 and 复活单王 are open). Read-only — changes nothing.
"""
from __future__ import annotations

import datetime as dt
import json

from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

NEW_ACCT = "act_1179668409969241"
SINCE = dt.date(2026, 9, 25)


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    token = result_action_type(s.meta.conversion_event)
    old_acct = s.meta.account_path
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    tr = json.dumps({"since": SINCE.isoformat(), "until": today.isoformat()})

    def daily(acct: str, title: str) -> float:
        log.info("═" * 104)
        log.info("%s", title)
        rows = g._get_all(f"{acct}/insights",
                          {"level": "account", "time_increment": 1, "limit": 100,
                           "fields": "spend,actions,inline_link_clicks", "time_range": tr})
        total = 0.0
        for r in rows:
            sp = float(r.get("spend") or 0)
            lc = float(r.get("inline_link_clicks") or 0)
            ld = extract_results(r.get("actions"), token)
            total += sp
            log.info("  %s  花 RM%-9.2f 链接点击 %-5d CPC %-8s leads %-4d CPL %-9s 点击→lead %s",
                     r.get("date_start"), sp, int(lc),
                     f"RM{sp / lc:.2f}" if lc else "—", int(ld),
                     f"RM{sp / ld:,.0f}" if ld else "—",
                     f"{ld / lc * 100:.1f}%" if lc else "—")
        if not rows:
            log.info("  （窗口内无消耗）")
        return total

    old_total = daily(old_acct, f"① 老账户 {old_acct} 逐日"
                                "（搬家前基线: CPC 7.2-7.7 · CPL 100+ · 点击→lead 0-3.6%）")
    new_total = daily(NEW_ACCT, f"② 新账户 {NEW_ACCT} 逐日")

    log.info("═" * 104)
    log.info("③ 新账户 今天（%s）分链", today)
    for r in g._get_all(f"{NEW_ACCT}/insights",
                        {"level": "adset", "limit": 100,
                         "fields": "adset_name,spend,actions,inline_link_clicks",
                         "time_range": json.dumps({"since": today.isoformat(),
                                                   "until": today.isoformat()})}):
        sp = float(r.get("spend") or 0)
        lc = float(r.get("inline_link_clicks") or 0)
        ld = extract_results(r.get("actions"), token)
        log.info("  ▸ %-38s 花 RM%-7.2f 点击 %-4d CPC %-8s %dL CPL %s",
                 (r.get("adset_name") or "?")[:38], sp, int(lc),
                 f"RM{sp / lc:.2f}" if lc else "—", int(ld),
                 f"RM{sp / ld:,.0f}" if ld else "—")

    log.info("═" * 104)
    log.info("④ 新户消耗上限检查")
    try:
        a = g.get_object(NEW_ACCT, "spend_cap,amount_spent,currency")
        cap = a.get("spend_cap")
        log.info("  账户 spend_cap: %s · 终身 amount_spent: RM%.2f",
                 "未设" if not cap or cap in ("0", 0) else f"RM{int(cap) / 100:.0f}",
                 int(a.get("amount_spent") or 0) / 100)
    except Exception as exc:  # noqa: BLE001
        log.info("  spend_cap 读不了: %s", str(exc)[:110])
    try:
        d = g.get_object(NEW_ACCT, "adtrust_dsl")
        log.info("  新户每日上限 adtrust_dsl: RM%s（今天实际花 vs 这个值）", d.get("adtrust_dsl"))
    except Exception as exc:  # noqa: BLE001
        log.info("  adtrust_dsl 读不了（权限限制属正常）: %s", str(exc)[:90])

    log.info("═" * 104)
    log.info("⑤ 新账户 审核/受限 + 各 campaign 开关")
    camps = g._get_all(f"{NEW_ACCT}/campaigns",
                       {"fields": "id,name,status,effective_status,daily_budget", "limit": 200})
    adsets = g._get_all(f"{NEW_ACCT}/adsets",
                        {"fields": "id,name,daily_budget,campaign_id", "limit": 500})
    ads = g._get_all(f"{NEW_ACCT}/ads",
                     {"fields": "id,name,effective_status,issues_info", "limit": 500})
    bad = [x for x in ads
           if x.get("effective_status") in ("DISAPPROVED", "WITH_ISSUES") or x.get("issues_info")]
    pend = [x for x in ads if x.get("effective_status") in ("IN_PROCESS", "PENDING_REVIEW")]
    for x in bad:
        log.info("  🚫 %s %r %s · issues %s", x["id"], (x.get("name") or "")[:42],
                 x.get("effective_status"),
                 json.dumps(x.get("issues_info") or [], ensure_ascii=False)[:150])
    log.info("  被拒/受限 %d 条 · 还在审核 %d 条（%s）", len(bad), len(pend),
             ", ".join((x.get("name") or "")[:24] for x in pend) or "—")
    for c in camps:
        b = int(c.get("daily_budget") or 0) or sum(
            int(x.get("daily_budget") or 0) for x in adsets if x.get("campaign_id") == c["id"])
        log.info("  ▸ %-15s RM%-4d %r", c.get("effective_status"), b // 100,
                 (c.get("name") or "")[:62])

    final_summary(log, f"A/B day-1 compare done: old acct RM{old_total:.0f} vs new acct "
                       f"RM{new_total:.0f} spend in {SINCE}→{today}; {len(bad)} restricted, "
                       f"{len(pend)} in review on the new account. Read-only.")


if __name__ == "__main__":
    main()
