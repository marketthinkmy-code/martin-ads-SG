"""Same creative, three markets (read-only, 9 Oct).

Operator: 新的广告在 MY 都有出 lead，就是新加坡不断测试都没有 — so before killing the SG
retests, line the SAME videos up across MY / HK / SG old and see which stage differs:
  CPM (flow cost) → link CPC / CTR (does the video earn the click) → 报名率 = leads ÷ link
  clicks (does the SG landing page convert) → CPL. Matched on content tokens, not names,
  because SG uses traditional and HK/MY simplified. 30d window, plus 10/1→today. No writes.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from collections import defaultdict
from typing import Dict, List

from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

ACCOUNTS = [("MY", "act_1011719073600566"), ("HK", "act_1179668409969241"), ("SG老", "act_1024930575770087")]
CREATIVES = [
    ("Video 2 長高了17cm", re.compile(r"17\s*cm", re.I)),
    ("Video 4 看舌頭", re.compile(r"看舌")),
    ("Video 3 15岁后不能长高", re.compile(r"15[岁歲][后後]")),
    ("Hook 2 上了中学没长高", re.compile(r"上了中[学學]")),
    ("Hook 3 16岁还长高", re.compile(r"16[岁歲]")),
    ("Video 1 KL&SG 線下見面", re.compile(r"[線线]下[見见]面")),
    ("参照 · 林書豪", re.compile(r"林[書书]豪")),
    ("参照 · 倒掉牛奶", re.compile(r"倒掉牛奶")),
]


def _f(x) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    token = result_action_type(s.meta.conversion_event)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    windows = {"30d": today - dt.timedelta(days=30), "10/1起": dt.date(2026, 10, 1)}

    def pull(acct: str, since: dt.date):
        agg: Dict[str, List[float]] = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0.0])  # spend, impr, clicks, leads, n_ads
        names: Dict[str, set] = defaultdict(set)
        for r in g._get_all(f"{acct}/insights",
                            {"level": "ad", "limit": 500,
                             "fields": "ad_id,ad_name,spend,impressions,inline_link_clicks,actions",
                             "time_range": json.dumps({"since": since.isoformat(), "until": today.isoformat()})}):
            nm = r.get("ad_name") or ""
            for label, pat in CREATIVES:
                if pat.search(nm):
                    a = agg[label]
                    a[0] += _f(r.get("spend")); a[1] += _f(r.get("impressions"))
                    a[2] += _f(r.get("inline_link_clicks")); a[3] += extract_results(r.get("actions"), token); a[4] += 1
                    names[label].add(nm[:34])
                    break
        return agg, names

    data = {w: {acct_label: pull(acct, since) for acct_label, acct in ACCOUNTS} for w, since in windows.items()}

    for w in windows:
        log.info("═" * 118)
        log.info("窗口 %s · 每格 = 花 / 曝光 / CPM / 链接点击 / 点击成本 / 点击率 / lead / 报名率(lead÷点击) / CPL", w)
        for label, _ in CREATIVES:
            log.info("▌%s", label)
            for acct_label, _acct in ACCOUNTS:
                sp, im, ck, ld, n = data[w][acct_label][0].get(label, [0, 0, 0, 0, 0])
                if not sp:
                    log.info("    %-4s —（没跑过 / 没花费）", acct_label)
                    continue
                log.info("    %-4s 花 RM%-8.2f 曝光 %-7d CPM RM%-6.2f 点击 %-4d CPC RM%-6.2f CTR %-5s lead %-3d 报名率 %-5s CPL %s · %d 支广告 %s",
                         acct_label, sp, int(im), sp / im * 1000 if im else 0, int(ck), sp / ck if ck else 0,
                         f"{ck / im * 100:.2f}%" if im else "—", int(ld), f"{ld / ck * 100:.0f}%" if ck else "—",
                         f"RM{sp / ld:,.0f}" if ld else "∞", int(n), sorted(data[w][acct_label][1].get(label, []))[:3])
    final_summary(log, "creative compare done · read-only")


if __name__ == "__main__":
    main()
