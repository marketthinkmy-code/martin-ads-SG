"""monitor: pause ads whose CPL exceeds the threshold."""

from __future__ import annotations

from typing import Any, Dict

import requests

from . import graph_client
from .. import monitor_cpl
from ..clients.graph import TransientGraphError
from ..logging import get_logger


def run(settings, *, dry_run: bool = False) -> Dict[str, Any]:
    graph = graph_client(settings)
    try:
        return monitor_cpl.run(graph, settings, dry_run=dry_run)
    except (TransientGraphError, requests.RequestException) as exc:
        # Meta had a transient outage (429/5xx/network blip) that outlived the client's
        # retries. This is an idempotent job that reruns every 20 min, so log and skip the
        # run cleanly — the next tick catches up. A passing upstream hiccup must never raise
        # a CI failure alarm; only real config/auth/code errors (which propagate) exit non-zero.
        get_logger().warning(
            "Meta API transiently unavailable after retries (%s) — skipping this run", exc)
        return {"evaluated": 0, "paused": 0, "remaining": 0, "dry_run": dry_run,
                "skipped": "meta_transient"}
