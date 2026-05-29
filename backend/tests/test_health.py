"""Phase 0 smoke tests: the app boots and the liveness route works (no DB needed)."""

from __future__ import annotations


async def test_health_liveness(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"


def test_trivial_passing():
    """The trivial passing test required by the Phase 0 DoD."""
    assert 1 + 1 == 2
