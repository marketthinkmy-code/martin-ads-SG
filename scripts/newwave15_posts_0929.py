"""New Wave 15 支新视频 · existing post ids (read-only, 29 Sep).

Operator: 給我 新廣告 15 個的 existing post id — 手动建广告用。

The 15 new videos were built as the 9/14 New Wave (3 campaigns × 15 single-ad ad sets,
45 ads, 15 unique names). Five of them re-ran as the 9/21 test and were ported to the
new account on 9/25 (those copies REUSED the old posts, so engagement is pooled).

① Every old-account ad created on 2026-09-14 → the 15 unique folded names.
② For each name: the newest copy on EITHER account whose creative carries
   effective_object_story_id → the post id to reuse.
③ Context per name: spend/leads/CPL folded across both accounts since 9/14.
Read-only.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from typing import Dict

from adbot import cpa
from adbot.clients.graph import GraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

NEW_ACCT = "act_1179668409969241"
BUILD_DAY = "2026-09-14"


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    token = result_action_type(s.meta.conversion_event)
    old_acct = s.meta.account_path
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    tr = json.dumps({"since": BUILD_DAY, "until": today.isoformat()})

    ads_index = []
    for acct, tag in ((old_acct, "老"), (NEW_ACCT, "新")):
        for a in g._get_all(f"{acct}/ads", {"fields": "id,name,created_time",
                                            "limit": 500}):
            ads_index.append((a.get("created_time") or "", tag, a["id"],
                              cpa.ad_key(a.get("name") or ""), (a.get("name") or "").strip()))
    ads_index.sort(reverse=True)

    names: Dict[str, str] = {}
    for created, tag, _i, k, disp in ads_index:
        if tag == "老" and created.startswith(BUILD_DAY) and k:
            names.setdefault(k, disp)
    log.info("9/14 New Wave 当日建的广告折叠出 %d 个名字（应为 15）", len(names))

    sp: Dict[str, float] = defaultdict(float)
    ld: Dict[str, float] = defaultdict(float)
    for acct in (old_acct, NEW_ACCT):
        for r in g._get_all(f"{acct}/insights",
                            {"level": "ad", "limit": 500, "time_range": tr,
                             "fields": "ad_id,ad_name,spend,actions"}):
            k = cpa.ad_key(r.get("ad_name") or "")
            if k not in names:
                continue
            try:
                sp[k] += float(r.get("spend") or 0)
            except (TypeError, ValueError):
                pass
            ld[k] += extract_results(r.get("actions"), token)

    def find_post(key: str):
        for created, tag, ad_id, k, _d in ads_index:
            if k != key:
                continue
            try:
                cr = (g.get_object(ad_id, "creative{effective_object_story_id}")
                      .get("creative") or {})
            except GraphError:
                continue
            pid = cr.get("effective_object_story_id")
            if pid:
                return pid, tag, created
        return None, None, None

    log.info("═" * 116)
    log.info("New Wave 15 支 · existing post ids（9/14 → %s 两账户合并花费；帖取最新可复用拷贝）", today)
    done = 0
    for k in sorted(names, key=lambda x: -sp.get(x, 0.0)):
        pid, tag, created = find_post(k)
        cpl = sp[k] / ld[k] if ld.get(k) else 0.0
        log.info("▸ %s", names[k])
        log.info("    POST ID: %s   （%s账户拷贝 · %s）· 9/14起 花 RM%.0f · %dL%s",
                 pid or "∅ 没有可复用的帖", tag or "-", (created or "")[:10],
                 sp.get(k, 0.0), int(ld.get(k, 0)),
                 f" · CPL RM{cpl:,.0f}" if ld.get(k) else "")
        if pid:
            done += 1
    final_summary(log, f"{done}/{len(names)} New Wave ads have reusable post ids. Read-only.")


if __name__ == "__main__":
    main()
