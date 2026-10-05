"""Delete the half-built QING 15岁+ campaign (operator, 5 Oct: 你先刪乾淨).

The cancelled build left campaign 120258782942310093 PAUSED with the Hook 2 and
Hook 3 ad sets/ads/creatives (Video 3 never got built). Remove all of it:
ads → ad sets → campaign via status=DELETED (house pattern, each guarded by a
lifetime-spend check: anything that ever spent is left alone and reported),
then the two creatives via DELETE. The two uploaded videos stay in the media
library (no cost, re-usable). State file is rewritten as a deletion record.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from adbot.clients.graph import GraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_PATH = Path("state") / "entities_qing15_1005.json"


def main() -> None:
    log = get_logger()
    g = graph_client(load_settings())
    st = json.loads(STATE_PATH.read_text())
    if st.get("deleted_at"):
        final_summary(log, f"already deleted at {st['deleted_at']} — nothing to do")
        return

    def spend(eid: str) -> float:
        try:
            rows = g._request("GET", f"{eid}/insights",
                              params={"fields": "spend", "date_preset": "maximum"}).get("data") or []
            return sum(float(r.get("spend") or 0) for r in rows)
        except GraphError as exc:
            log.info("  (insights unavailable for %s: %s — treating as 0)", eid, exc)
            return 0.0

    done, kept = [], []
    plan = ([("ad", i) for i in st.get("ads", {}).values()]
            + [("adset", i) for i in st.get("adsets", {}).values()]
            + [("campaign", st["campaign_id"])] if st.get("campaign_id") else [])
    for kind, eid in plan:
        try:
            before = g.get_object(eid, "name,effective_status")
        except GraphError as exc:
            log.info("  %s %s already gone (%s)", kind, eid, exc)
            continue
        sp = spend(eid)
        if sp > 0:
            kept.append(f"{kind} {eid} spent RM{sp:.2f}")
            log.info("  ⚠️ %s %s %r spent RM%.2f — NOT deleted", kind, eid, before.get("name"), sp)
            continue
        g._request("POST", eid, data={"status": "DELETED"})
        after = g.get_object(eid, "effective_status").get("effective_status")
        log.info("  🗑 %s %s %r → %s", kind, eid, before.get("name"), after)
        done.append(f"{kind}:{eid}")
    for key, cid in (st.get("creatives") or {}).items():
        try:
            g._request("DELETE", cid)
            log.info("  🗑 creative %s (%s) deleted", cid, key)
            done.append(f"creative:{cid}")
        except GraphError as exc:
            log.info("  creative %s (%s) delete failed: %s", cid, key, exc)
            kept.append(f"creative {cid}: {exc}")

    st["deleted_at"] = dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    st["deleted"] = done
    st["kept"] = kept
    STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))
    final_summary(log, f"QING 15岁+ cleanup: deleted {len(done)} · kept {kept or 'none'} · "
                       f"videos left in library: {[v['video_id'] for v in st.get('videos', {}).values()]}")


if __name__ == "__main__":
    main()
