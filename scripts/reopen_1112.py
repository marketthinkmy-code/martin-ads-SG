"""Reopen the ads the operator switched off at ~3 pm on 11 Nov, at 00:00 MYT 12 Nov (operator 11/11 21:4x).

Operator: 「帮我把我3pm左右关掉的广告 or 你认为值得开回去的广告 等下 00:00 帮我开回去。」 The seven SG老户 ads that
were live at 13:38 SGT (adbot-cycle-check run 10) and off at 15:32 (run 11):
  Hook 2：旧鞋当尺 120258189814070093 · Video 2：長高了17cm 120258845193530093 ·
  什麼樣的孩子基本上不會再長高 120256984988770093 · Food and Drink + Milk 11月新片: Video 8 120259459021510093,
  Video 7 120259459017220093, Video 5 120259459004440093, Video 2：吃完就马上去厕所？ 120259458992280093.
Nothing else is opened. Ads the monitor paused (Video 1 / 3 / 6) and ads the operator paused earlier stay off.
For each target: ad, its ad set and its campaign are set ACTIVE (ad first, campaign last). Before a parent is
switched on, any OTHER ad under it whose own status is ACTIVE (it would start delivering with the parent) is
set PAUSED first, so nothing besides the seven starts. Budgets are not touched.
ADBOT_MODE=check (default): read-only preview of every change. ADBOT_MODE=go: wait until
2026-11-12 00:00 +08:00 (the job sleeps), then switch on and read everything back.
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import time

from adbot.clients.graph import TransientGraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

# operator 11/11 ~23:35 「B」: Video 2：吃完就马上去厕所？ 120259458992280093 stays off (weakest CPL, its 1 lead scored 50)
TARGETS = ["120258189814070093", "120258845193530093", "120256984988770093", "120259459021510093",
           "120259459017220093", "120259459004440093"]
AT = dt.datetime(2026, 11, 12, 0, 0, tzinfo=dt.timezone(dt.timedelta(hours=8)))


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    go = (os.environ.get("ADBOT_MODE") or "check").strip().lower() == "go"
    if go:
        wait = (AT - dt.datetime.now(dt.timezone.utc)).total_seconds()
        log.info("等到 %s（还有 %.0f 分钟）再开", AT.isoformat(), max(wait, 0) / 60)
        while wait > 0:
            time.sleep(min(wait, 300))
            wait = (AT - dt.datetime.now(dt.timezone.utc)).total_seconds()
    tset = set(TARGETS)
    info, adsets, camps = {}, {}, {}
    for ad_id in TARGETS:
        a = g.get_object(ad_id, "name,account_id,status,effective_status,adset{id,name,status,daily_budget},"
                                "campaign{id,name,status,daily_budget}")
        if str(a.get("account_id")) != "1024930575770087":
            log.error("❌ %s 不在 SG老户，停止。", ad_id)
            sys.exit(1)
        info[ad_id] = a
        adsets[a["adset"]["id"]] = a["adset"]
        camps[a["campaign"]["id"]] = a["campaign"]
        log.info("  目标 %s %r · ad %s · ad set %s %r %s（日预算 %s）· campaign %s %r %s（日预算 %s）", ad_id, a.get("name"),
                 a.get("status"), a["adset"]["id"], a["adset"].get("name"), a["adset"].get("status"),
                 a["adset"].get("daily_budget"), a["campaign"]["id"], a["campaign"].get("name", "")[:60],
                 a["campaign"].get("status"), a["campaign"].get("daily_budget"))

    # siblings that would start with their parent: own status ACTIVE, not a target
    guard = []
    for cid, c in camps.items():
        for x in g._get_all(f"{cid}/ads", {"fields": "id,name,status,adset{id,status}", "limit": 200}):
            if x["id"] in tset or x.get("status") != "ACTIVE":
                continue
            parent_off = c.get("status") != "ACTIVE" or (x.get("adset") or {}).get("id") in adsets
            if parent_off:
                guard.append(x)
    for x in guard:
        log.info("  %s 同 campaign / ad set 的 %s %r 自己是 ACTIVE，母层一开就会跑 → 先设 PAUSED（它现在本来就没在跑）",
                 "将" if not go else "", x["id"], x.get("name"))
    if not go:
        final_summary(log, f"预览（只读）：开 {len(TARGETS)} 支广告、{len(adsets)} 个 ad set、{len(camps)} 个 campaign；"
                           f"先关 {len(guard)} 支同层的其他广告（避免一起跑）。没有改任何东西。")
        return

    for x in guard:
        g.update_status(x["id"], "PAUSED")
        time.sleep(0.5)
    for ad_id in TARGETS:
        if info[ad_id].get("status") != "ACTIVE":
            g.update_status(ad_id, "ACTIVE")
            time.sleep(0.5)
    for sid, a_s in adsets.items():
        if a_s.get("status") != "ACTIVE":
            g.update_status(sid, "ACTIVE")
            time.sleep(0.5)
    for cid, c in camps.items():
        if c.get("status") != "ACTIVE":
            g.update_status(cid, "ACTIVE")
            time.sleep(0.5)
    time.sleep(5)
    log.info("═" * 100)
    ok = 0
    for ad_id in TARGETS:
        a = g.get_object(ad_id, "name,status,effective_status")
        ok += a.get("effective_status") == "ACTIVE"
        log.info("  %s %r · %s / %s", ad_id, a.get("name"), a.get("status"), a.get("effective_status"))
    for x in guard:
        a = g.get_object(x["id"], "name,status,effective_status")
        log.info("  （同层其他广告保持不跑）%s %r · %s / %s", x["id"], a.get("name"), a.get("status"), a.get("effective_status"))
    final_summary(log, f"00:00 开回 {ok}/{len(TARGETS)} 支（effective ACTIVE）· 同层其他广告 {len(guard)} 支保持关")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s", str(exc)[:200])
        sys.exit(75)
