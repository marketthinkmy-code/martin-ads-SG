"""Lock Advantage Audience OFF on the 15 New Wave 0914 F&R ad sets.

The operator's approved spec: F&R clones the 16-sale source with "Adv+OFF · 18-65 照抄，
锁死防 Meta 偷改". The source ad set (120257269400410093) returns NO targeting_automation
field — the analysis digest displays that as Adv+OFF, but clone_targeting's None→1 default
created the 15 new F&R ad sets with advantage_audience=1. This pass rewrites each of them
with the same cloned spec plus an explicit advantage_audience=0 and re-reads to verify,
skipping sets already at 0 (idempotent, safe to re-dispatch after a rate limit).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict

from adbot.clients.graph import TransientGraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

sys.path.insert(0, str(Path(__file__).parent))
from build_new_wave_0914 import STATE_PATH, clone_targeting  # noqa: E402

FR_SOURCE = "120257269400410093"


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)

    st: Dict[str, Any] = json.loads(STATE_PATH.read_text())
    fr = st["campaigns"]["fr"]
    units = fr["units"]

    spec = clone_targeting(g, FR_SOURCE, s)
    spec["targeting_automation"] = {"advantage_audience": 0}
    payload = json.dumps(spec)
    log.info("Corrected F&R spec: ages %s-%s · Adv+ OFF (explicit 0) · %d flexible_spec",
             spec.get("age_min"), spec.get("age_max"), len(spec.get("flexible_spec") or []))

    fixed = already = failed = 0
    try:
        for key, rec in units.items():
            aid = rec.get("adset_id")
            if not aid:
                continue
            t = g._request("GET", aid, params={"fields": "targeting"}).get("targeting") or {}
            adv = (t.get("targeting_automation") or {}).get("advantage_audience")
            if int(adv or 0) == 0 and adv is not None:
                log.info("  %-6s adset %s already Adv+ OFF", key, aid)
                already += 1
                continue
            g._request("POST", aid, data={"targeting": payload})
            t2 = g._request("GET", aid, params={"fields": "targeting"}).get("targeting") or {}
            adv2 = int((t2.get("targeting_automation") or {}).get("advantage_audience") or 0)
            if adv2 == 0:
                log.info("  %-6s adset %s: Adv+ %s → OFF ✓", key, aid,
                         "ON" if int(adv or 0) else "unset")
                fixed += 1
            else:
                log.error("  %-6s adset %s: rewrite did NOT stick (adv=%s)", key, aid, adv2)
                failed += 1
            time.sleep(1.0)
    finally:
        fr["source_adset"]["adv"] = 0
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))

    if failed:
        log.error("%d ad sets still have expansion ON — fix by hand or re-dispatch", failed)
        sys.exit(1)
    final_summary(log, f"F&R New Wave ad sets locked Adv+ OFF: {fixed} rewritten, "
                       f"{already} already off, 0 failed (of {len(units)}). The other two "
                       f"campaigns stay Adv+ ON as their sources really are.")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — re-dispatch in ~30 min; pass is idempotent.", exc)
        sys.exit(75)
