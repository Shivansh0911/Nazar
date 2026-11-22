"""API smoke test against the dev database with the demo data (python scripts/demo_setup.py)."""
import pytest
from fastapi.testclient import TestClient

from nazar.core import db
from nazar.core.config import get_settings

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def client():
    from nazar.api.main import app

    s = get_settings()
    s.AUTO_START_EDGES = False
    with TestClient(app) as c:
        tok = c.post("/api/auth", json={"passcode": s.DEMO_PASSCODE}).json()["token"]
        c.headers["X-Nazar-Token"] = tok
        c.token = tok
        yield c


@pytest.fixture(scope="module")
def cam(client):
    cams = client.get("/api/cameras").json()
    with_data = [c for c in cams if c["coverage_from"]]
    if not with_data:
        pytest.skip("no demo data - run scripts/demo_setup.py")
    return with_data[0]


def test_auth_required():
    from nazar.api.main import app

    with TestClient(app) as c:
        assert c.get("/api/cameras").status_code == 401
        assert c.post("/api/auth", json={"passcode": "nope"}).status_code == 401
        assert c.get("/api/health").status_code == 200


def test_cameras_and_timeline(client, cam):
    assert {"id", "live", "today_count", "coverage_from", "zones"} <= set(cam)
    t = client.get(f"/api/cameras/{cam['id']}/timeline", params={"from": cam["coverage_from"], "to": cam["coverage_to"]}).json()
    assert t["level"] == "confirmed" and t["value"] >= 1
    assert sum(p["n"] for p in t["series"]) == t["value"]
    g = client.get(f"/api/cameras/{cam['id']}/gaps", params={"from": cam["coverage_from"], "to": cam["coverage_to"]}).json()
    assert "gaps" in g


def test_count_matches_sql(client, cam):
    r = client.get("/api/count", params={"camera_id": cam["id"], "event": "present", "from": cam["coverage_from"],
                                         "to": cam["coverage_to"]}).json()
    sql = db.fetch_val("SELECT count(*) FROM root_tracks WHERE camera_id=%s AND cls='person' AND t_end >= %s AND t_start <= %s "
                       "AND t_end - t_start >= interval '1.5 seconds' AND COALESCE(max_conf, 1) >= 0.6 AND rider_of IS NULL",
                       (cam["id"], cam["coverage_from"], cam["coverage_to"]))
    assert r["value"] == sql
    assert len(r["_receipts"]) == r["value"]  # every counted track is a receipt
    assert sum(p["n"] for p in r["series"]) == r["value"]


def test_structural_search_is_confirmed(client, cam):
    r = client.get("/api/search", params={"camera_id": cam["id"], "from": cam["coverage_from"], "to": cam["coverage_to"],
                                          "cls": "person"}).json()
    assert r["results"] and all(x["level"] == "confirmed" for x in r["results"])
    tid = r["results"][0]["track_id"]
    tr = client.get(f"/api/tracks/{tid}").json()
    assert tr["path"] and tr["crops"]
    img = client.get("/media/" + tr["crops"][0].split("/media/", 1)[1])
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"


def test_clip_for_track(client, cam):
    r = client.get("/api/search", params={"camera_id": cam["id"], "from": cam["coverage_from"], "to": cam["coverage_to"],
                                          "cls": "person"}).json()
    tid = max(r["results"], key=lambda x: x["t_end"])["track_id"]
    c = client.get(f"/api/clips/track/{tid}").json()
    assert c["url"] and c["t1_ms"] > c["t0_ms"] and isinstance(c["path"], list)
    v = client.get("/media/" + c["url"].split("/media/", 1)[1])
    assert v.status_code == 200 and v.headers["content-type"] == "video/mp4" and len(v.content) > 1000


def test_snapshot_rules_alerts_metrics(client, cam):
    s = client.get(f"/api/cameras/{cam['id']}/snapshot.jpg")
    assert s.status_code == 200 and s.content[:2] == b"\xff\xd8"
    assert isinstance(client.get("/api/rules").json(), list)
    assert isinstance(client.get("/api/alerts").json(), list)
    m = client.get("/api/metrics").json()
    assert m["tracks_processed"] > 0 and m["footage_hours"] > 0


def test_ai_routes_without_key(client, cam, monkeypatch):
    if get_settings().has_openai:
        pytest.skip("key present")
    r = client.post("/api/ask", json={"text": "Aaj kitne log aaye?"})
    assert r.status_code == 503 and r.json() == {"error": "OPENAI_API_KEY not set"}
    r = client.post(f"/api/cameras/{cam['id']}/suggest-zones")
    assert r.status_code == 503


def test_camera_source_validation(client):
    bad = client.post("/api/cameras", json={"name": "x", "source_url": "http://169.254.169.254/latest", "start": False})
    assert bad.status_code == 400
    meta = client.post("/api/cameras", json={"name": "x", "source_url": "rtsp://169.254.169.254/x", "start": False})
    assert meta.status_code == 400
    outside = client.post("/api/cameras", json={"name": "x", "source_url": "C:/Windows/win.ini", "start": False})
    assert outside.status_code == 400
    ok = client.post("/api/cameras", json={"name": "Smoke RTSP", "source_url": "rtsp://localhost:8554/smoke", "start": False})
    assert ok.status_code == 200 and ok.json()["kind"] == "rtsp"
    assert client.delete(f"/api/cameras/{ok.json()['id']}").status_code == 200
