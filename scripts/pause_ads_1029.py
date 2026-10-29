"""Pause the ads named in ADBOT_AD_IDS (operator 29 Oct 「现在关掉 #12 和 #16 和 Video 5」) and read each back.

Ad level only; ad sets / campaigns are left as they are. 75 = Meta throttled, safe to re-run.
"""
from __future__ import annotations

import os
import sys

from adbot.clients.graph import GraphError, TransientGraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

DEFAULT = "120258109011660093,120256985982080093,120250236479810335"  # #12 SG老户 Video 12 · #16 SG老户 Video 7 · HK Video 5


def main():
    log = get_logger()
    g = graph_client(load_settings())
    ids = [x.strip() for x in (os.environ.get("ADBOT_AD_IDS") or DEFAULT).split(",") if x.strip()]
    done, failed = [], []
    for aid in ids:
        try:
            g.update_status(aid, "PAUSED")
            a = g.get_object(aid, "name,status,effective_status,account_id")
            done.append(f"act_{a.get('account_id')} {aid} {a.get('status')}")
            log.info("⏸ act_%s ad %s %r → %s / %s", a.get("account_id"), aid, a.get("name"), a.get("status"),
                     a.get("effective_status"))
        except TransientGraphError:
            raise
        except GraphError as exc:
            failed.append(aid)
            log.error("❌ ad %s 关不了：%s", aid, str(exc)[:200])
    final_summary(log, f"关掉 {len(done)} 支 · 失败 {len(failed)} · {' | '.join(done)}" + (f" · 失败 {failed}" if failed else ""))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — re-dispatch in ~30 min (safe to re-run).", str(exc)[:200])
        sys.exit(75)
