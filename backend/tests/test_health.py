async def test_health_returns_ok(client):
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
