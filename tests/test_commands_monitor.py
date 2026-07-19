"""commands.monitor.run: a transient Meta outage skips cleanly; real errors still surface.

The CPL monitor is an idempotent cron (every 20 min). When Meta has a passing 5xx/network
blip that outlives the GraphClient's retries, the run must degrade to a clean skip (exit 0)
so it doesn't fire a CI failure alarm — the next tick catches up. A genuine config/auth/code
error must still propagate so a real misconfiguration is loud, not silently skipped forever.
"""
import pytest
import requests

from adbot.clients.graph import GraphError, TransientGraphError
from adbot.commands import monitor
from adbot.settings import Settings


def _raise(exc):
    def _run(graph, settings, *, dry_run=False):
        raise exc
    return _run


def test_transient_graph_error_skips_cleanly(monkeypatch):
    # HTTP 500 is_transient that exhausted the client's 5 retries -> reraised TransientGraphError.
    monkeypatch.setattr(monitor.monitor_cpl, "run",
                        _raise(TransientGraphError("HTTP 500: is_transient")))
    out = monitor.run(Settings(), dry_run=False)
    assert out["skipped"] == "meta_transient"
    assert out["paused"] == 0 and out["evaluated"] == 0


def test_transient_network_error_skips_cleanly(monkeypatch):
    # A raw network blip on the un-retried pagination follow is the same transient class.
    monkeypatch.setattr(monitor.monitor_cpl, "run",
                        _raise(requests.ConnectionError("connection reset by peer")))
    assert monitor.run(Settings())["skipped"] == "meta_transient"


def test_genuine_graph_error_still_propagates(monkeypatch):
    # Bad token / 4xx config error must NOT be swallowed — the cron should fail loudly.
    monkeypatch.setattr(monitor.monitor_cpl, "run",
                        _raise(GraphError(400, {"error": {"message": "Invalid OAuth access token"}})))
    with pytest.raises(GraphError):
        monitor.run(Settings())


def test_code_bug_still_propagates(monkeypatch):
    # A programming error (not upstream-transient) must surface, never masquerade as a skip.
    monkeypatch.setattr(monitor.monitor_cpl, "run", _raise(KeyError("ad_id")))
    with pytest.raises(KeyError):
        monitor.run(Settings())
