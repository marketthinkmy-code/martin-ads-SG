"""Open Hook 7 担心孩子的高度 in BROAD WOMEN (operator: 幫我開, 1 Oct).

The ad is the list's best 30d CPA (RM320 · 1 sale · last sale 9/23) and the only
paused ad in the BROAD WOMEN ad set. Flip it ACTIVE; everything above it is already
ACTIVE. Idempotent — activating an active ad is a no-op.
"""
from __future__ import annotations

from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

AD_ID = "120250046125990335"   # Hook 7: 担心孩子的高度没跟得上年龄该有的高度 @ BROAD WOMEN


def main() -> None:
    log = get_logger()
    g = graph_client(load_settings())
    before = g.get_object(AD_ID, "name,status,effective_status")
    log.info("before: %r %s/%s", before.get("name"), before.get("status"),
             before.get("effective_status"))
    if before.get("status") != "ACTIVE":
        g._request("POST", AD_ID, data={"status": "ACTIVE"})
    after = g.get_object(AD_ID, "name,status,effective_status")
    log.info("after:  %r %s/%s", after.get("name"), after.get("status"),
             after.get("effective_status"))
    final_summary(log, f"Hook 7 担心孩子的高度 @ BROAD WOMEN → {after.get('status')}/"
                       f"{after.get('effective_status')}.")


if __name__ == "__main__":
    main()
