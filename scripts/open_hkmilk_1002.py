"""Reopen HK MILK campaign (operator, 2 Oct): hk 的 milk 今天有成绩，继续开着.

The full-HK pause (completing the operator's stuck shutdown) also closed MILK;
the operator wants MILK running — today RM102 / 2 regs / CPL ~51. Reactivate the
campaign whose name contains 'MILK' from the pause record; everything else stays
paused. Idempotent.
"""
from __future__ import annotations

import json
from pathlib import Path

from adbot import cpa
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_PATH = Path("state") / "hk_pause_1002.json"


def main() -> None:
    log = get_logger()
    g = graph_client(load_settings())
    st = json.loads(STATE_PATH.read_text())
    opened = []
    for cid, name in list(st.get("paused", {}).items()):
        if "milk" not in cpa.norm(name or ""):
            continue
        g._request("POST", cid, data={"status": "ACTIVE"})
        after = g.get_object(cid, "status,effective_status")
        log.info("▶️ %s %r → %s/%s", cid, name, after.get("status"),
                 after.get("effective_status"))
        opened.append(cid)
        st["paused"].pop(cid, None)
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))
    final_summary(log, f"HK MILK reopened: {opened or '找不到 MILK 记录'}; "
                       f"{len(st.get('paused', {}))} campaigns remain paused.")


if __name__ == "__main__":
    main()
