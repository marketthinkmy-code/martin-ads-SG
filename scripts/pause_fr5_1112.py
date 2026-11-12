"""Family and Relationships 11月新片7支: pause five ads + their ad sets, keep Video 8 and Video 5 (12 Nov).

Operator 12 Nov 「B」 after the since-launch read (adbot-newvid-life run 43173731721): in SG老户 campaign
120259499514770093 all seven ads had 0 registrations after one day; Video 3 (CTR 0.50%), Video 7 (0.48%),
Video 1 (0.97%), Video 2 (1.53%), Video 6 (1.73%) go off; Video 8 (2.99%) and Video 5 (2.48%) stay on.
Each listed ad and its ad set are set PAUSED (ABO: one ad per ad set). Campaign and budgets untouched.
ADBOT_MODE=check (default) previews; go writes and reads everything in the campaign back.
"""
from __future__ import annotations

import os
import sys
import time

from adbot.clients.graph import TransientGraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

CAMP = "120259499514770093"
OFF = {  # video: (ad, ad set)
    "Video 3：完蛋了！": ("120259499582010093", "120259499581440093"),
    "Video 7：父母试过一切共情": ("120259499588450093", "120259499587670093"),
    "Video 1：是谁说的？": ("120259499578780093", "120259499577750093"),
    "Video 2：吃完就马上去厕所？": ("120259499580340093", "120259499579720093"),
    "Video 6：具体数字目标": ("120259499586400093", "120259499585160093"),
}
KEEP = {"120259499590830093", "120259499583580093"}  # Video 8, Video 5


def main():
    log = get_logger()
    g = graph_client(load_settings())
    go = (os.environ.get("ADBOT_MODE") or "check").strip().lower() == "go"
    for v, (ad, aset) in OFF.items():
        a = g.get_object(ad, "name,account_id,campaign_id,adset_id,status")
        if str(a.get("account_id")) != "1024930575770087" or a.get("campaign_id") != CAMP or a.get("adset_id") != aset:
            log.error("❌ %s ad %s 不在预期的 SG老户 campaign / ad set（%s），停止，什么都没改。", v, ad, a)
            sys.exit(1)
        log.info("  %s %s · ad %s %r %s · ad set %s", "关" if go else "将关", v, ad, a.get("name"), a.get("status"), aset)
    if not go:
        final_summary(log, f"预览（只读）：将关 {len(OFF)} 支 ad + ad set，留 Video 8 / Video 5。没有改任何东西。")
        return
    for v, (ad, aset) in OFF.items():
        g.update_status(ad, "PAUSED")
        time.sleep(0.5)
        g.update_status(aset, "PAUSED")
        time.sleep(0.5)
    time.sleep(5)
    log.info("═" * 100)
    on = 0
    for x in g._get_all(f"{CAMP}/ads", {"fields": "id,name,status,effective_status,adset{id,status}", "limit": 50}):
        on += x.get("effective_status") == "ACTIVE"
        log.info("  ad %s %r · ad %s / %s · ad set %s %s%s", x["id"], x.get("name"), x.get("status"), x.get("effective_status"),
                 (x.get("adset") or {}).get("id"), (x.get("adset") or {}).get("status"), "（留）" if x["id"] in KEEP else "")
    c = g.get_object(CAMP, "status,effective_status")
    final_summary(log, f"Family and Relationships 11月新片7支：关了 {len(OFF)} 支，还在跑 {on} 支 · campaign {c.get('status')}/{c.get('effective_status')}")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s", str(exc)[:200])
        sys.exit(75)
