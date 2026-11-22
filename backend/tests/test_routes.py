"""Every API route against the dev database with the demo data: auth, status codes, response shapes, error paths.
Routes that call OpenAI are marked `live`. Run: pytest -q tests/test_routes.py  (needs Postgres + demo data)."""
import io
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from nazar.core import db
from nazar.core.config import get_settings

pytestmark = pytest.mark.db
PUBLIC = {("POST", "/api/auth"), ("GET", "/api/health")}
SUB = {"camera_id": "office-desk", "track_id": "1", "rule_id": "1", "alert_id": "1", "query_id": "1", "upload_id": "x",
       "index": "0", "obj_id": "1", "name": "x.mp3", "fmt": "csv", "key": "x.jpg"}


@pytest.fixture(scope="module")
def app():
    get_settings().AUTO_START_EDGES = False
    from nazar.api.main import app as a
    return a


@pytest.fixture(scope="module")
def c(app):
    with TestClient(app) as cl:
        cl.headers["X-Nazar-Token"] = cl.post("/api/auth", json={"passcode": get_settings().DEMO_PASSCODE}).json()["token"]
        yield cl


@pytest.fixture(scope="module")
def ids():
    tr = db.fetch_one("SELECT id, camera_id FROM root_tracks WHERE cls='person' AND crop_keys <> '{}' AND NOT active "
                      "AND camera_id='office-desk' ORDER BY t_end - t_start DESC LIMIT 1")
    cov = db.fetch_one("SELECT min(t_start) AS a, max(t_end) AS b FROM coverage WHERE camera_id='office-desk'")
    if not tr or not cov or not cov["a"]:
        pytest.skip("demo data missing - run scripts/demo_setup.py")
    return {"track": tr["id"], "from": cov["a"].isoformat(), "to": cov["b"].isoformat(),
            "alert": db.fetch_val("SELECT max(id) FROM alerts"), "rule": db.fetch_val("SELECT max(id) FROM rules")}


# --- auth -------------------------------------------------------------------------------------------------------
def test_every_route_needs_a_token_except_public(app):
    with TestClient(app) as anon:
        for p, ops in app.openapi()["paths"].items():
            url = p
            for k, v in SUB.items():
                url = url.replace("{" + k + "}", v)
            for m in ops:
                if (m.upper(), p) in PUBLIC or url.endswith(".mjpg"):
                    continue
                assert anon.request(m.upper(), url).status_code == 401, f"{m.upper()} {p} is not protected"


def test_auth_rejects_wrong_passcode_and_bad_token(app):
    with TestClient(app) as anon:
        assert anon.post("/api/auth", json={"passcode": "wrong"}).status_code == 401
        assert anon.post("/api/auth", json={}).status_code == 422
        assert anon.get("/api/cameras", headers={"X-Nazar-Token": "forged.token"}).status_code == 401
        assert anon.get("/api/health").json().get("ok") in (True, None)


# --- cameras ----------------------------------------------------------------------------------------------------
def test_cameras_list_detail_and_404(c):
    cams = c.get("/api/cameras").json()
    assert any(x["id"] == "office-desk" for x in cams)
    one = c.get("/api/cameras/office-desk").json()
    assert one["id"] == "office-desk" and "zones" in one
    assert c.get("/api/cameras/no-such-cam").status_code == 404
    assert c.patch("/api/cameras/no-such-cam", json={"name": "x"}).status_code == 404


def test_camera_create_patch_delete_roundtrip(c):
    r = c.post("/api/cameras", json={"id": "pytest-cam", "name": "Pytest cam", "source_url": "rtsp://10.255.255.1/x",
                                     "kind": "rtsp", "start": False})
    assert r.status_code in (200, 201), r.text
    try:
        assert c.patch("/api/cameras/pytest-cam", json={"name": "Renamed",
                                                         "zones": [{"name": "z1", "label": "Z1",
                                                                    "polygon": [[0, 0], [1, 0], [1, 1]]}]}).status_code == 200
        got = c.get("/api/cameras/pytest-cam").json()
        assert got["name"] == "Renamed" and got["zones"][0]["name"] == "z1"
        assert c.post("/api/cameras", json={"id": "pytest-cam", "name": "dup", "source_url": "x"}).status_code in (400, 409)
    finally:
        assert c.delete("/api/cameras/pytest-cam").status_code in (200, 204)
    assert c.get("/api/cameras/pytest-cam").status_code == 404


def test_camera_timeline_gaps_tracks_progress_edge(c, ids):
    q = {"from": ids["from"], "to": ids["to"]}
    t = c.get("/api/cameras/office-desk/timeline", params=q).json()
    assert t["level"] == "confirmed" and sum(p["n"] for p in t["series"]) == t["value"]
    assert "gaps" in c.get("/api/cameras/office-desk/gaps", params=q).json()
    tracks = c.get("/api/cameras/office-desk/tracks", params={"limit": 5}).json()
    assert isinstance(tracks, (list, dict))
    assert c.get("/api/cameras/office-desk/progress").status_code == 200
    assert c.get("/api/cameras/office-desk/edge").status_code == 200
    assert c.get("/api/cameras/office-desk/timeline", params={"from": "not-a-date", "to": ids["to"]}).status_code in (400, 422)


def test_snapshot_is_a_jpeg(c):
    r = c.get("/api/cameras/office-desk/snapshot.jpg")
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        assert r.content[:2] == b"\xff\xd8"


def test_onboarding_presets_test_template_import(c):
    pre = c.get("/api/cameras/presets").json()
    assert pre and any("hik" in str(p).lower() for p in (pre if isinstance(pre, list) else pre.values()))
    r = c.post("/api/cameras/test", json={"ip": "10.255.255.1", "brand": "hikvision", "username": "admin", "password": "x"},
               timeout=60).json()
    assert r.get("ok") is False and r.get("error", "").split(" ")[0] in ("unreachable", "auth", "wrong", "no")
    assert r.get("url_preview", "").startswith("rtsp://10.255.255.1")
    # /api/cameras/rtsp ADDS the camera: create it inactive (no edge), check the stored URL hides the password, delete it
    made = c.post("/api/cameras/rtsp", json={"name": "Pytest DVR", "brand": "hikvision", "ip": "192.168.1.64",
                                             "username": "admin", "password": "p@ss", "channel": 1, "stream": "sub",
                                             "active": False})
    assert made.status_code == 200, made.text
    cam_id = made.json().get("id") or made.json().get("camera_id")
    try:
        assert "p@ss" not in c.get(f"/api/cameras/{cam_id}").text      # password encrypted, never returned
    finally:
        c.post(f"/api/cameras/{cam_id}/stop")
        assert c.delete(f"/api/cameras/{cam_id}").status_code in (200, 204)
    tpl = c.get("/api/cameras/import/template.csv")
    assert tpl.status_code == 200 and b"name" in tpl.content.lower()
    assert c.get("/api/cameras/import/template.xlsx").status_code == 200
    assert c.get("/api/cameras/import/template.pdf").status_code in (400, 404, 422)
    csv = b"name,rtsp_url\nGate,rtsp://10.255.255.1:554/x\n"
    imp = c.post("/api/cameras/import", files={"file": ("cams.csv", io.BytesIO(csv), "text/csv")}, timeout=120)
    assert imp.status_code == 200, imp.text
    body = imp.json()
    assert body.get("import_id") and len(body.get("rows", [])) == 1


def test_phone_setup_and_discover(c):
    r = c.get("/api/phone-setup/office-desk")
    assert r.status_code == 200 and ("srt" in r.text.lower() or "rtmp" in r.text.lower())
    assert c.get("/api/cameras/discover", params={"seconds": 1}, timeout=30).status_code == 200


# --- counts, search, tracks, clips ------------------------------------------------------------------------------
def test_count_equals_sql_and_receipts(c, ids):
    r = c.get("/api/count", params={"camera_id": "office-desk", "event": "present", "from": ids["from"], "to": ids["to"]}).json()
    sql = db.fetch_val("SELECT count(*) FROM root_tracks WHERE camera_id='office-desk' AND cls='person' AND t_end >= %s "
                       "AND t_start <= %s AND t_end - t_start >= interval '1.5 seconds' AND COALESCE(max_conf,1) >= 0.6 "
                       "AND rider_of IS NULL", (ids["from"], ids["to"]))
    assert r["value"] == sql and len(r["_receipts"]) == r["value"] and r["level"] == "confirmed"
    assert c.get("/api/count", params={"camera_id": "office-desk", "from": "bad"}).status_code in (400, 422)


def test_search_tracks_similar_journey(c, ids):
    s = c.get("/api/search", params={"camera_id": "office-desk", "cls": "person", "from": ids["from"], "to": ids["to"]}).json()
    assert isinstance(s, (list, dict))
    t = c.get(f"/api/tracks/{ids['track']}").json()
    assert t["track_id"] == ids["track"] and t["camera_id"] == "office-desk" and t["crops"]
    assert c.get("/api/tracks/999999999").status_code == 404
    assert c.get(f"/api/tracks/{ids['track']}/similar").status_code == 200
    j = c.get(f"/api/journey/{ids['track']}", timeout=120)
    assert j.status_code == 200
    assert c.get("/api/journey/999999999").status_code == 404


def _probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=codec_name,pix_fmt,width,height", "-of", "default=nw=1", path], capture_output=True, text=True)
    d = dict(line.split("=", 1) for line in out.stdout.strip().splitlines())
    return d["codec_name"], d["pix_fmt"], d["width"], d["height"]


def test_clip_for_track_is_h264_yuv420p_even_and_not_black(c, ids, tmp_path):
    r = c.get(f"/api/clips/track/{ids['track']}", timeout=180)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["url"] and body["t1_ms"] > body["t0_ms"] and body["path"]
    data = c.get(body["url"]).content
    mp4 = tmp_path / "c.mp4"
    mp4.write_bytes(data)
    codec, pix, w, h = _probe(str(mp4))
    assert codec == "h264" and pix == "yuv420p" and int(w) % 2 == 0 and int(h) % 2 == 0
    assert data.find(b"moov") < data.find(b"mdat"), "moov atom must come first (faststart)"
    for ss in ("0.2", "50%"):
        if ss == "50%":
            dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                        str(mp4)], capture_output=True, text=True).stdout or 2)
            ss = f"{dur / 2:.2f}"
        luma = subprocess.run(["ffmpeg", "-v", "error", "-ss", ss, "-i", str(mp4), "-frames:v", "1", "-vf",
                               "scale=64:36,format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout
        assert luma and sum(luma) / len(luma) > 10, f"black frame at {ss}"
    assert c.get("/api/clips/track/999999999").status_code == 404


def test_clip_range_reel_and_media(c, ids):
    r = c.get("/api/clips/range", params={"camera_id": "office-desk", "from": ids["from"],
                                          "to": ids["from"].replace("+", "+")}, timeout=180)
    assert r.status_code in (200, 400, 404, 422)
    reel = c.post("/api/clips/reel", json={"track_ids": [ids["track"]], "total": 5}, timeout=240)
    assert reel.status_code == 200, reel.text
    assert c.get(reel.json()["url"]).content[:12].find(b"ftyp") >= 0
    assert c.get("/media/../../etc/passwd").status_code in (400, 404)
    assert c.get("/media/no/such/file.jpg").status_code == 404


# --- rules, alerts, receipts, feedback ---------------------------------------------------------------------------
def test_rules_alerts_listing_and_errors(c, ids):
    rules = c.get("/api/rules").json()
    assert isinstance(rules, list)
    alerts = c.get("/api/alerts", params={"limit": 5}).json()
    assert isinstance(alerts, list) and len(alerts) <= 5
    if alerts:
        assert {"id", "camera_id", "t", "message"} <= set(alerts[0])
        assert c.post(f"/api/alerts/{alerts[0]['id']}/ack").status_code == 200
    assert c.post("/api/rules/999999999/activate").status_code == 404
    assert c.post("/api/rules/999999999/deactivate").status_code == 404
    assert c.delete("/api/rules/999999999").status_code == 404
    assert c.post("/api/alerts/999999999/ack").status_code == 404


def test_receipts_and_feedback(c):
    q = db.fetch_one("SELECT id FROM queries WHERE answer::text LIKE '%%receipts%%' ORDER BY id DESC LIMIT 1")
    if q:
        r = c.get(f"/api/receipts/{q['id']}", params={"page": 1, "size": 10})
        assert r.status_code == 200
    assert c.get("/api/receipts/999999999").status_code == 404
    tr = db.fetch_val("SELECT id FROM tracks ORDER BY id DESC LIMIT 1")
    assert c.post("/api/feedback", json={"kind": "receipt", "ref": str(tr), "correct": True}).status_code == 200
    assert c.post("/api/feedback", json={"kind": "receipt"}).status_code == 422


# --- uploads (no edge started: init + part + status only) ------------------------------------------------------
def test_upload_init_part_status(c):
    data = b"\x00" * 1024
    r = c.post("/api/uploads/init", json={"filename": "pytest.mp4", "size": len(data), "name": "pytest upload"})
    assert r.status_code == 200, r.text
    up = r.json()
    uid = up.get("upload_id") or up.get("id")
    assert c.put(f"/api/uploads/{uid}/part/0", content=data).status_code == 200
    st = c.get(f"/api/uploads/{uid}").json()
    assert st.get("received", st.get("parts")) is not None
    assert c.get("/api/uploads/does-not-exist").status_code in (400, 404)
    assert c.post("/api/uploads/init", json={"filename": "x.exe", "size": 10}).status_code in (400, 415, 422)


# --- v2: visual search, security, reports, settings, telegram, custom objects ----------------------------------
def test_visual_search_text_and_photo_audit(c):
    r = c.post("/api/search/visual", data={"text": "person carrying a bag", "limit": "5"}, timeout=120)
    assert r.status_code in (200, 503), r.text   # 503 when the vision service is not running
    if r.status_code == 200:
        assert len(r.json().get("hits", [])) <= 5
    assert c.post("/api/search/visual", data={}).status_code in (400, 422)
    assert c.get("/api/photo-searches", params={"limit": 3}).status_code == 200


def test_security_digest_reports_settings_pair(c):
    ev = c.get("/api/sec-events", params={"limit": 5}).json()
    assert isinstance(ev, list) and all({"type", "level"} <= set(e) for e in ev)
    assert all(e["level"] in ("confirmed", "probable", "candidate") for e in ev)
    assert c.get("/api/digest", params={"voice": "false"}).status_code == 200
    assert isinstance(c.get("/api/reports").json(), list)
    s = c.get("/api/settings").json()
    assert "openai" not in str(s).lower() or "sk-" not in str(s)          # never leaks a key
    code = c.post("/api/telegram/pair-code").json()
    assert len(str(code.get("code"))) == 6
    assert c.get("/api/analysis/office-desk/live").status_code in (200, 404)
    assert c.get("/api/metrics").status_code == 200


def test_custom_object_create_list_delete(c):
    r = c.post("/api/custom-objects", json={"camera_id": "office-desk", "name": "pytest kettle", "alert": False}, timeout=60)
    assert r.status_code == 200, r.text
    oid = r.json().get("object_id")
    assert any(o["id"] == oid for o in c.get("/api/custom-objects", params={"camera_id": "office-desk"}).json())
    assert c.delete(f"/api/custom-objects/{oid}").status_code == 200
    assert c.delete("/api/custom-objects/999999999").status_code == 404
    assert c.post("/api/custom-objects", json={"camera_id": "no-such-cam", "name": "x"}).status_code in (400, 404, 422)


# --- OpenAI-backed routes ---------------------------------------------------------------------------------------
@pytest.mark.live
def test_ask_stream_and_audio(c, ids):
    r = c.post("/api/ask", json={"text": "Office desk pe kitne log dikhe?", "camera_id": "office-desk"}, timeout=180)
    assert r.status_code == 200, r.text
    a = r.json()
    assert a.get("text") or a.get("answer")
    with c.stream("POST", "/api/ask/stream", json={"text": "How many people at the office desk?"}, timeout=180) as s:
        assert s.status_code == 200
        body = b"".join(s.iter_bytes())
    assert b"data:" in body
    assert c.get("/api/ask/audio/bad name.mp3").status_code in (400, 404)


@pytest.mark.live
def test_rule_compile_and_report(c, ids):
    r = c.post("/api/rules/compile", json={"text": "Jab bhi koi desk 14 se bag uthaye, mujhe batana",
                                           "camera_id": "office-desk"}, timeout=180)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["spec"]["trigger"] in ("object_removed", "zone_exit", "zone_enter") and "replay" in d
    if d.get("id"):
        assert c.delete(f"/api/rules/{d['id']}").status_code == 200
    if ids["alert"]:
        t = time.time()
        rep = c.post("/api/reports", json={"title": "pytest report", "alert_id": ids["alert"], "language": "hi"},
                     timeout=400).json()
        assert rep.get("pdf_url") and rep.get("preview_url"), rep
        pdf = c.get(rep["pdf_url"]).content
        assert pdf[:4] == b"%PDF" and time.time() - t < 400
