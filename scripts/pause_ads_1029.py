"""Pause the ads named in ADBOT_AD_IDS (operator 29 Oct 「现在关掉 #12 和 #16 和 Video 5」) and read each back.

Then (operator 29 Oct 「campaign 也关掉，不要保留 ad set / ad off 但是 campaign 开着」) every campaign of
those ads with no live ad left is paused, and ADBOT_SWEEP (default on) does the same for every ACTIVE
campaign on SG old + HK. 75 = Meta throttled, safe to re-run.
"""
from __future__ import annotations

import os
import sys

from adbot.clients.graph import GraphError, TransientGraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import close_empty_campaigns
from adbot.settings import load_settings

ACCTS = ["act_1024930575770087", "act_1179668409969241"]  # SG老户, HK
DEFAULT = "120258109011660093,120256985982080093,120250236479810335"  # #12 SG老户 Video 12 · #16 SG老户 Video 7 · HK Video 5


def main():
    log = get_logger()
    g = graph_client(load_settings())
    ids = [x.strip() for x in (os.environ.get("ADBOT_AD_IDS") or DEFAULT).split(",") if x.strip()]
    done, failed, camps = [], [], []
    for aid in ids:
        try:
            g.update_status(aid, "PAUSED")
            a = g.get_object(aid, "name,status,effective_status,account_id,campaign_id")
            camps.append(a.get("campaign_id"))
            done.append(f"act_{a.get('account_id')} {aid} {a.get('status')}")
            log.info("⏸ act_%s ad %s %r → %s / %s", a.get("account_id"), aid, a.get("name"), a.get("status"),
                     a.get("effective_status"))
        except TransientGraphError:
            raise
        except GraphError as exc:
            failed.append(aid)
            log.error("❌ ad %s 关不了：%s", aid, str(exc)[:200])
    closed = close_empty_campaigns(g, camps, ids, dry_run=False)
    if (os.environ.get("ADBOT_SWEEP") or "1") != "0":
        for acct in ACCTS:
            active = [c["id"] for c in g.list_campaigns(acct) if c.get("effective_status") == "ACTIVE"]
            closed += close_empty_campaigns(g, active, ids, dry_run=False)
    for cid in closed:
        c = g.get_object(cid, "name,status,account_id")
        log.info("⏸ campaign act_%s %s %r → %s", c.get("account_id"), cid, c.get("name"), c.get("status"))
    final_summary(log, f"关掉 {len(done)} 支广告 · 关掉没有在跑广告的 campaign {len(closed)} 个 · 失败 {len(failed)} · "
                       f"{' | '.join(done)}" + (f" · 失败 {failed}" if failed else ""))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — re-dispatch in ~30 min (safe to re-run).", str(exc)[:200])
        sys.exit(75)
