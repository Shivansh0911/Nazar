"""FIR-ready incident report (W5): HTML -> PDF with Playwright/Chromium (correct Devanagari shaping).

Contents: case title, camera/location, time window, timeline table, 4-8 face-blurred keyframes, an AI description
(marked AI-generated), evidence levels and how they were decided, the clip link, SHA-256 of the exported clip and of
the manifest, generation time and a "no face recognition used" note. Hindi or English.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from psycopg.types.json import Jsonb

from ..core import db, storage
from ..core.timeutil import to_local

log = logging.getLogger("nazar.reports")

L = {
    "en": {"title": "Incident report", "camera": "Camera", "location": "Location", "window": "Time window",
           "generated": "Generated", "timeline": "Timeline", "time": "Time", "what": "What", "level": "Evidence level",
           "frames": "Key frames (faces blurred)", "ai": "AI description (AI-generated - verify against the clip)",
           "levels": "How evidence levels are decided", "files": "Exported files and SHA-256 hashes", "file": "File",
           "clip": "Clip", "manifest": "Manifest SHA-256", "privacy": "No face recognition was used. Faces are blurred in every "
           "frame and clip. Identification, if any, must be done by the authorities from the original recording.",
           "confirmed": "Confirmed - recorded by the tracker (time, place, count).",
           "probable": "Probable - visual similarity AND an independent AI check agree.",
           "candidate": "Candidate - similarity or a heuristic only; needs a human check.", "none": "No description",
           "case": "Case"},
    "hi": {"title": "घटना रिपोर्ट", "camera": "कैमरा", "location": "स्थान", "window": "समय", "generated": "रिपोर्ट बनाई गई",
           "timeline": "घटनाक्रम", "time": "समय", "what": "क्या हुआ", "level": "प्रमाण स्तर",
           "frames": "मुख्य फ्रेम (चेहरे धुंधले)", "ai": "AI विवरण (AI द्वारा लिखा - क्लिप से मिलान करें)",
           "levels": "प्रमाण स्तर कैसे तय होते हैं", "files": "फ़ाइलें और SHA-256 हैश", "file": "फ़ाइल", "clip": "क्लिप",
           "manifest": "मैनिफ़ेस्ट SHA-256", "privacy": "चेहरा पहचान (face recognition) का उपयोग नहीं किया गया। हर फ्रेम और क्लिप में "
           "चेहरे धुंधले हैं। पहचान, यदि आवश्यक हो, अधिकारी मूल रिकॉर्डिंग से करें।",
           "confirmed": "पक्का (Confirmed) - ट्रैकर का रिकॉर्ड (समय, जगह, गिनती)।",
           "probable": "संभावित (Probable) - दिखावट की समानता और AI जाँच दोनों सहमत।",
           "candidate": "जाँचें (Candidate) - केवल समानता या अनुमान; इंसान से जाँच ज़रूरी।", "none": "कोई विवरण नहीं",
           "case": "केस"},
}
WHAT = {"enter": ("entered", "प्रवेश"), "exit": ("left", "बाहर गया"), "dwell": ("stayed", "रुका"),
        "cross_in": ("came in", "अंदर आया"), "cross_out": ("went out", "बाहर गया")}


def _sha(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sources(alert_id, sec_event_id, track_ids) -> tuple[str, list[int], datetime, datetime, list[dict]]:
    """camera, track ids, window, timeline seed rows."""
    rows: list[dict] = []
    if alert_id:
        a = db.fetch_one("SELECT a.*, r.text AS rule_text FROM alerts a JOIN rules r ON r.id=a.rule_id WHERE a.id=%s", (alert_id,))
        if not a:
            raise ValueError("alert not found")
        tids = [a["track_id"]] + [v for k, v in (a["meta"] or {}).items() if k.endswith("track_id") and isinstance(v, int)]
        rows.append({"t": a["t"], "what": f"ALERT: {a['message']}", "level": "confirmed"})
        cam = a["camera_id"]
        t0 = t1 = a["t"]
    elif sec_event_id:
        e = db.fetch_one("SELECT * FROM sec_events WHERE id=%s", (sec_event_id,))
        if not e:
            raise ValueError("security event not found")
        tids = list(e["track_ids"] or [])
        rows.append({"t": e["t_start"], "what": f"{e['type'].replace('_', ' ')}: {e['reason']}", "level": e["level"]})
        cam, t0, t1 = e["camera_id"], e["t_start"], e["t_end"]
    elif track_ids:
        tids = [int(t) for t in track_ids][:20]
        trs = db.fetch_all("SELECT camera_id, t_start, t_end FROM tracks WHERE id = ANY(%s)", (tids,))
        if not trs:
            raise ValueError("tracks not found")
        cam = trs[0]["camera_id"]
        t0, t1 = min(t["t_start"] for t in trs), max(t["t_end"] for t in trs)
    else:
        raise ValueError("give an alert, a security event or tracks")
    trs = db.fetch_all("SELECT id, cls, t_start, t_end FROM tracks WHERE id = ANY(%s)", (tids,))
    if trs:
        t0 = min([t0] + [t["t_start"] for t in trs])
        t1 = max([t1] + [t["t_end"] for t in trs])
    return cam, tids, t0 - timedelta(seconds=5), t1 + timedelta(seconds=5), rows


def create_report(*, title: str, alert_id=None, sec_event_id=None, track_ids=None, language: str = "en",
                  token: str | None = None, describe: bool = True) -> dict:
    lang = "hi" if language == "hi" else "en"
    tx = L[lang]
    cam_id, tids, t0, t1, rows = _sources(alert_id, sec_event_id, track_ids)
    cam = db.fetch_one("SELECT id, name, location FROM cameras WHERE id=%s", (cam_id,)) or {"id": cam_id, "name": cam_id, "location": None}
    rid = db.fetch_one("INSERT INTO reports(title, language, source) VALUES (%s,%s,%s) RETURNING id",
                       (title[:200], lang, Jsonb({"alert_id": alert_id, "sec_event_id": sec_event_id, "track_ids": tids})))["id"]
    ref = f"report:{rid}"
    # timeline: tracker events of the involved tracks + security events in the window
    for e in db.fetch_all("SELECT e.type, e.zone, e.t, t.cls FROM events e JOIN tracks t ON t.id=e.track_id WHERE "
                          "(e.track_id = ANY(%s) OR t.merged_into = ANY(%s)) ORDER BY e.t LIMIT 40", (tids, tids)):
        w = WHAT.get(e["type"], (e["type"], e["type"]))[0 if lang == "en" else 1]
        rows.append({"t": e["t"], "what": f"{e['cls']} {w} {e['zone'].replace('_', ' ')}", "level": "confirmed"})
    for s in db.fetch_all("SELECT type, t_start, level, reason FROM sec_events WHERE camera_id=%s AND t_start BETWEEN %s AND %s",
                          (cam_id, t0, t1)):
        if not any(r["t"] == s["t_start"] for r in rows):
            rows.append({"t": s["t_start"], "what": f"{s['type'].replace('_', ' ')}: {s['reason']}", "level": s["level"]})
    for t in db.fetch_all("SELECT id, cls, t_start, t_end FROM tracks WHERE id = ANY(%s)", (tids,)):
        rows.append({"t": t["t_start"], "what": f"{t['cls']} #{t['id']} first seen", "level": "confirmed"})
        rows.append({"t": t["t_end"], "what": f"{t['cls']} #{t['id']} last seen", "level": "confirmed"})
    rows.sort(key=lambda r: r["t"])
    # frames: blurred keyframes in the window (+ crops of the involved tracks)
    kfs = [r["key"] for r in db.fetch_all("SELECT key FROM keyframes WHERE camera_id=%s AND t BETWEEN %s AND %s ORDER BY t",
                                          (cam_id, t0, t1))]
    if len(kfs) > 6:
        kfs = [kfs[round(i * (len(kfs) - 1) / 5)] for i in range(6)]
    crops = []
    for t in db.fetch_all("SELECT crop_keys FROM tracks WHERE id = ANY(%s)", (tids,)):
        if t["crop_keys"]:
            crops.append(t["crop_keys"][0])
    frames = [k for k in kfs + crops[:2] if storage.local_path(k).exists()][:8]
    # AI description (marked as AI-generated)
    desc = None
    if describe and tids:
        try:
            from .agent_tools2 import describe_clip

            d = describe_clip({"track_id": tids[0]}, ref)
            desc = d.get("description")
        except Exception as e:
            log.warning("report description failed: %s", e)
    # clip + hashes
    files = []
    clip_url = None
    try:
        from .clips import cut

        c = cut(cam_id, t0, min(t1, t0 + timedelta(seconds=60)))
        p = storage.local_path(c["key"])
        files.append({"name": f"clip_{rid}.mp4", "key": c["key"], "sha256": _sha(p), "bytes": p.stat().st_size})
        clip_url = storage.url(c["key"], token)
    except Exception as e:
        log.warning("report clip failed: %s", e)
    for k in frames:
        files.append({"name": k.rsplit("/", 1)[-1], "key": k, "sha256": _sha(storage.local_path(k))})
    generated = to_local(datetime.now(timezone.utc))
    manifest = {"report_id": rid, "title": title, "camera": cam_id, "window": [to_local(t0).isoformat(), to_local(t1).isoformat()],
                "generated_at": generated.isoformat(), "files": [{k: f[k] for k in ("name", "sha256")} for f in files],
                "face_recognition": False}
    man_bytes = json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode()
    man_sha = hashlib.sha256(man_bytes).hexdigest()
    storage.put_bytes(man_bytes, f"reports/{rid}_manifest.json")

    def img(k):
        return "data:image/jpeg;base64," + base64.b64encode(storage.local_path(k).read_bytes()).decode()

    def esc(s):
        return html.escape(str(s))

    lvl_cls = {"confirmed": "c", "probable": "p", "candidate": "d"}
    timeline_html = "".join(
        f"<tr><td>{esc(to_local(r['t']).strftime('%d %b %H:%M:%S'))}</td><td>{esc(r['what'])}</td>"
        f"<td><span class='lv {lvl_cls.get(r['level'], 'd')}'>{esc(r['level'])}</span></td></tr>" for r in rows[:60])
    frames_html = "".join(f"<figure><img src='{img(k)}'/><figcaption>{esc(k.rsplit('/', 1)[-1])}</figcaption></figure>" for k in frames)
    files_html = "".join(f"<tr><td>{esc(f['name'])}</td><td class='mono'>{f['sha256']}</td></tr>" for f in files)
    doc = f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><style>
    body{{font-family:'Noto Sans Devanagari','Nirmala UI','Mangal','Segoe UI',Arial,sans-serif;color:#0b1222;margin:28px;font-size:12px}}
    h1{{font-size:22px;margin:0}} h2{{font-size:14px;margin:22px 0 8px;border-bottom:1px solid #dde3ee;padding-bottom:4px}}
    .meta{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:12px}} .meta div{{background:#f3f5fa;border-radius:8px;padding:8px}}
    .meta b{{display:block;font-size:10px;color:#5b6680;text-transform:uppercase}} table{{width:100%;border-collapse:collapse}}
    td,th{{border-bottom:1px solid #e6eaf2;padding:5px 6px;text-align:left;vertical-align:top}} .mono{{font-family:Consolas,monospace;font-size:9px;word-break:break-all}}
    .lv{{border-radius:10px;padding:1px 7px;font-size:10px}} .c{{background:#10b981;color:#fff}} .p{{background:#fef3c7;color:#92400e;border:1px solid #f59e0b}}
    .d{{border:1px dashed #64748b;color:#334155}} .frames{{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}}
    figure{{margin:0}} figure img{{width:100%;border-radius:6px}} figcaption{{font-size:8px;color:#5b6680}}
    .ai{{border:1px dashed #94a3b8;border-radius:8px;padding:8px;background:#f8fafc}} .brand{{color:#2f6bff;font-weight:700}}
    .foot{{margin-top:20px;font-size:10px;color:#5b6680}}</style></head><body>
    <div class="brand">NAZAR</div><h1>{esc(tx['title'])}: {esc(title)}</h1>
    <div class="meta"><div><b>{esc(tx['case'])}</b>#{rid}</div><div><b>{esc(tx['camera'])}</b>{esc(cam['name'])}</div>
    <div><b>{esc(tx['location'])}</b>{esc(cam.get('location') or '—')}</div>
    <div><b>{esc(tx['window'])}</b>{to_local(t0):%d %b %Y %H:%M:%S} – {to_local(t1):%H:%M:%S}</div></div>
    <h2>{esc(tx['timeline'])}</h2><table><tr><th>{esc(tx['time'])}</th><th>{esc(tx['what'])}</th><th>{esc(tx['level'])}</th></tr>{timeline_html}</table>
    <h2>{esc(tx['frames'])}</h2><div class="frames">{frames_html}</div>
    <h2>{esc(tx['ai'])}</h2><div class="ai">{esc(desc or tx['none'])}</div>
    <h2>{esc(tx['levels'])}</h2><p><span class="lv c">confirmed</span> {esc(tx['confirmed'])}<br/><span class="lv p">probable</span> {esc(tx['probable'])}<br/>
    <span class="lv d">candidate</span> {esc(tx['candidate'])}</p>
    <h2>{esc(tx['files'])}</h2><table><tr><th>{esc(tx['file'])}</th><th>SHA-256</th></tr>{files_html}</table>
    <p><b>{esc(tx['manifest'])}:</b> <span class="mono">{man_sha}</span></p>
    <p class="foot">{esc(tx['privacy'])}<br/>{esc(tx['generated'])}: {generated:%d %b %Y %H:%M:%S} IST · Nazar</p></body></html>"""
    from playwright.sync_api import sync_playwright

    pdf_key = f"reports/{rid}_{uuid.uuid4().hex[:6]}.pdf"
    out = storage.local_path(pdf_key)
    out.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.set_content(doc, wait_until="load")
        pg.set_viewport_size({"width": 900, "height": 1200})
        prev = storage.local_path(f"reports/{rid}_preview.png")
        pg.screenshot(path=str(prev), full_page=True)  # first-page preview for the app (and Telegram)
        pg.pdf(path=str(out), format="A4", print_background=True, margin={"top": "12mm", "bottom": "12mm", "left": "8mm", "right": "8mm"})
        b.close()
    storage.put(out, pdf_key)
    db.execute("UPDATE reports SET pdf_key=%s, manifest_sha256=%s WHERE id=%s", (pdf_key, man_sha, rid))
    return {"ok": True, "report_id": rid, "title": title, "pdf_url": storage.url(pdf_key, token), "manifest_sha256": man_sha,
            "preview_url": storage.url(f"reports/{rid}_preview.png", token),
            "clip_url": clip_url, "frames": len(frames), "timeline_rows": len(rows), "pdf_key": pdf_key}
