"""Onboarding (W9.3-9.5): CCTV/RTSP builder with brand presets and Test connection, Excel/CSV bulk import with
concurrent probing, and LAN discovery (ONVIF WS-Discovery). Passwords are encrypted at rest, never returned."""
from __future__ import annotations

import base64
import csv
import io
import re
import socket
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..core import db
from ..core.config import ffmpeg_bin, ffprobe_bin
from ..core.secrets import save_camera_credentials, split_credentials, with_credentials
from ..core.security import SourceError, validate_source
from .auth import require_token
from .deps import http_error
from .edge_manager import get_manager
from .routes_cameras import camera_rows, slug, unique_id

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])
PRESETS = {
    "hikvision": {"label": "Hikvision", "port": 554, "path": "/Streaming/Channels/{channel}0{stream_no}",
                  "note": "main stream 101, sub stream 102"},
    "dahua": {"label": "Dahua", "port": 554, "path": "/cam/realmonitor?channel={channel}&subtype={subtype}",
              "note": "subtype 0 = main, 1 = sub"},
    "cpplus": {"label": "CP Plus", "port": 554, "path": "/cam/realmonitor?channel={channel}&subtype={subtype}",
               "note": "same as Dahua"},
    "godrej": {"label": "Godrej / other", "port": 554, "path": None, "note": "paste the RTSP URL from the DVR manual"},
    "custom": {"label": "Custom URL", "port": 554, "path": None, "note": "any rtsp:// srt:// rtmp:// URL"},
}
TEMPLATE_COLS = ["name", "location", "brand", "ip", "port", "username", "password", "channel", "stream", "rtsp_url",
                 "zone_template", "active"]
_imports: dict[str, dict] = {}


class CamSpec(BaseModel):
    name: str = Field("", max_length=60)
    location: str | None = Field(None, max_length=80)
    brand: str = "custom"
    ip: str | None = None
    port: int | None = None
    username: str | None = None
    password: str | None = None
    channel: int | None = 1
    stream: str | None = "sub"  # main | sub
    rtsp_url: str | None = None
    active: bool = True


def build_url(c: CamSpec) -> str:
    """Full URL (with credentials, never stored or returned as-is)."""
    if c.rtsp_url:
        base, u, p = split_credentials(c.rtsp_url.strip())
        return with_credentials(base, c.username or u, c.password or p)
    pr = PRESETS.get((c.brand or "custom").lower().replace(" ", ""))
    if not pr or not pr["path"] or not c.ip:
        raise ValueError("enter the camera IP (or a full RTSP URL for this brand)")
    if not re.fullmatch(r"[A-Za-z0-9.\-:]+", c.ip):
        raise ValueError("bad IP / host")
    main = (c.stream or "sub").lower().startswith("main")
    path = pr["path"].format(channel=c.channel or 1, stream_no=1 if main else 2, subtype=0 if main else 1)
    return with_credentials(f"rtsp://{c.ip}:{c.port or pr['port']}{path}", c.username, c.password)


def classify(err: str) -> str:
    e = err.lower()
    if "401" in e or "unauthorized" in e or "authorization" in e:
        return "auth failed - check the username/password"
    if "404" in e or "not found" in e or "stream not found" in e or "454" in e:
        return "wrong path - the camera answered but has no stream at that path/channel"
    if "timed out" in e or "timeout" in e or "connection refused" in e or "unreachable" in e or "no route" in e:
        return "unreachable - check the IP/port and that this computer is on the same network"
    if "resolve" in e or "name or service" in e:
        return "cannot resolve that host"
    return (err.strip().splitlines() or ["could not open the stream"])[-1][:160]


def probe_stream(url: str, timeout_s: float = 8.0) -> dict:
    """ffprobe (8 s) -> codec, size, fps + a face-blurred thumbnail, or a precise error."""
    try:
        validate_source(split_credentials(url)[0])
    except SourceError as e:
        return {"ok": False, "error": str(e)}
    t0 = time.monotonic()
    to_us = str(int(timeout_s * 1_000_000))
    cmd = [ffprobe_bin(), "-v", "error", "-rtsp_transport", "tcp", "-timeout", to_us, "-select_streams", "v:0",
           "-show_entries", "stream=codec_name,width,height,avg_frame_rate", "-of", "csv=p=0", url]
    if not url.lower().startswith("rtsp"):
        cmd = [x for x in cmd if x not in ("-rtsp_transport", "tcp")]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s + 4)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "unreachable - no answer within 8 s"}
    if r.returncode != 0 or not r.stdout.strip():
        return {"ok": False, "error": classify(r.stderr or "no video stream")}
    parts = r.stdout.strip().splitlines()[0].split(",")
    codec, w, h = parts[0], int(parts[1] or 0), int(parts[2] or 0)
    fps = None
    try:
        n, d = parts[3].split("/")
        fps = round(float(n) / float(d), 1) if float(d) else None
    except Exception:
        pass
    thumb = None
    try:
        args = [ffmpeg_bin(), "-v", "error"] + (["-rtsp_transport", "tcp"] if url.lower().startswith("rtsp") else []) + \
               ["-timeout", to_us, "-i", url, "-frames:v", "1", "-vf", "scale=480:-2", "-f", "image2pipe", "-vcodec", "mjpeg", "-"]
        img = subprocess.run(args, capture_output=True, timeout=timeout_s + 4).stdout
        frame = cv2.imdecode(np.frombuffer(img, np.uint8), cv2.IMREAD_COLOR) if img else None
        if frame is not None:
            from ..edge.faceblur import FaceBlurrer

            frame = FaceBlurrer().egress(frame, [], detect=True)
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if ok:
                thumb = "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()
    except Exception:
        pass
    return {"ok": True, "codec": codec, "width": w, "height": h, "fps": fps, "thumbnail": thumb,
            "ms": int((time.monotonic() - t0) * 1000)}


@router.get("/cameras/presets")
def presets():
    return [{"id": k, **v} for k, v in PRESETS.items()]


@router.post("/cameras/test")
def test_connection(c: CamSpec):
    try:
        url = build_url(c)
    except ValueError as e:
        raise http_error(400, str(e))
    return {**probe_stream(url), "url_preview": split_credentials(url)[0]}


def add_camera(c: CamSpec, start: bool = True) -> dict:
    url = build_url(c)
    base, user, pw = split_credentials(url)
    try:
        base, kind = validate_source(base)
    except SourceError as e:
        raise ValueError(str(e))
    cid = unique_id(slug(c.name or c.location or "cctv"))
    db.execute("INSERT INTO cameras(id, name, source_url, kind, brand, location, ip, port, channel, stream, active) "
               "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
               (cid, (c.name or c.location or "CCTV").strip()[:60], base, kind, c.brand, c.location, c.ip, c.port,
                c.channel, c.stream, c.active))
    save_camera_credentials(db, cid, user, pw)
    status = get_manager().start(cid, live=True) if (start and c.active) else None
    return {**camera_rows(cid)[0], "edge_status": status}


@router.post("/cameras/rtsp")
def create_rtsp(c: CamSpec):
    try:
        return add_camera(c)
    except ValueError as e:
        raise http_error(400, str(e))


# ---- Excel / CSV bulk import --------------------------------------------------------------------------
@router.get("/cameras/import/template.{fmt}")
def template(fmt: str):
    example = [["Shop counter", "Main bazaar shop", "hikvision", "192.168.1.64", "554", "admin", "", "1", "sub", "",
                "", "yes"],
               ["Back door", "Godown", "dahua", "192.168.1.65", "554", "admin", "", "2", "sub", "", "", "yes"],
               ["Gate (custom)", "Society gate", "custom", "", "", "", "", "", "", "rtsp://192.168.1.70:554/stream1", "", "yes"]]
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(TEMPLATE_COLS)
        w.writerows(example)
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": "attachment; filename=nazar_cameras.csv"})
    if fmt == "xlsx":
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "cameras"
        ws.append(TEMPLATE_COLS)
        for row in example:
            ws.append(row)
        for col, width in zip("ABCDEFGHIJKL", (18, 20, 12, 15, 6, 10, 10, 8, 8, 34, 14, 7)):
            ws.column_dimensions[col].width = width
        out = io.BytesIO()
        wb.save(out)
        return Response(out.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": "attachment; filename=nazar_cameras.xlsx"})
    raise http_error(404, "use template.xlsx or template.csv")


def _rows_from(data: bytes, filename: str) -> list[dict]:
    if filename.lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        it = ws.iter_rows(values_only=True)
        header = [str(h or "").strip().lower() for h in next(it, [])]
        return [{header[i]: ("" if v is None else str(v).strip()) for i, v in enumerate(r) if i < len(header)}
                for r in it if any(v not in (None, "") for v in r)]
    text = data.decode("utf-8-sig", errors="replace")
    rd = csv.DictReader(io.StringIO(text))
    return [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in rd if any((v or "").strip() for v in r.values())]


def _spec(r: dict) -> CamSpec:
    def num(v):
        try:
            return int(float(v)) if str(v).strip() else None
        except ValueError:
            raise ValueError(f"'{v}' is not a number")

    return CamSpec(name=r.get("name", "")[:60], location=r.get("location") or None, brand=(r.get("brand") or "custom").lower(),
                   ip=r.get("ip") or None, port=num(r.get("port", "")), username=r.get("username") or None,
                   password=r.get("password") or None, channel=num(r.get("channel", "")) or 1,
                   stream=r.get("stream") or "sub", rtsp_url=r.get("rtsp_url") or None,
                   active=(r.get("active", "yes") or "yes").lower() not in ("no", "false", "0", "n"))


@router.post("/cameras/import")
async def import_cameras(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > 2 * 1024 * 1024:
        raise http_error(413, "file too large")
    try:
        rows = _rows_from(data, file.filename or "cameras.csv")
    except Exception as e:
        raise http_error(400, f"could not read the sheet: {e}")
    if not rows:
        raise http_error(400, "no rows found (use the template)")
    if len(rows) > 64:
        raise http_error(400, "max 64 cameras per import")
    parsed: list[tuple[int, CamSpec | None, str | None]] = []
    for i, r in enumerate(rows):
        try:
            c = _spec(r)
            build_url(c)
            if not c.name:
                raise ValueError("name is required")
            parsed.append((i, c, None))
        except Exception as e:
            parsed.append((i, None, str(e)))

    def probe_row(item):
        i, c, err = item
        if err:
            return {"row": i + 2, "ok": False, "error": err}
        res = probe_stream(build_url(c))
        return {"row": i + 2, "name": c.name, "brand": c.brand, "url_preview": split_credentials(build_url(c))[0],
                **res}

    with ThreadPoolExecutor(max_workers=4) as pool:  # probe at most 4 cameras at a time
        results = list(pool.map(probe_row, parsed))
    iid = uuid.uuid4().hex
    _imports[iid] = {"at": time.time(), "specs": {i + 2: c for i, c, err in parsed if c is not None}}
    for k in [k for k, v in _imports.items() if time.time() - v["at"] > 1800]:
        _imports.pop(k, None)
    return {"import_id": iid, "rows": results, "working": sum(1 for r in results if r.get("ok"))}


class CommitIn(BaseModel):
    import_id: str
    rows: list[int]


@router.post("/cameras/import/commit")
def import_commit(body: CommitIn):
    imp = _imports.get(body.import_id)
    if not imp:
        raise http_error(404, "import expired - upload the sheet again")
    added, errors = [], []
    for row in body.rows:
        c = imp["specs"].get(row)
        if c is None:
            errors.append({"row": row, "error": "not a valid row"})
            continue
        try:
            added.append(add_camera(c))
        except Exception as e:
            errors.append({"row": row, "error": str(e)[:200]})
    _imports.pop(body.import_id, None)
    return {"added": added, "errors": errors}


# ---- LAN discovery (ONVIF WS-Discovery) ---------------------------------------------------------------
PROBE = """<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope" xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
 xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery" xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
<e:Header><w:MessageID>uuid:{mid}</w:MessageID><w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
<w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action></e:Header>
<e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body></e:Envelope>"""


@router.get("/cameras/discover")
def discover(seconds: float = 3.0):
    """Find ONVIF cameras/DVRs on this network (IP + maker) to prefill the builder."""
    found: dict[str, dict] = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(0.5)
        sock.sendto(PROBE.format(mid=uuid.uuid4()).encode(), ("239.255.255.250", 3702))
        end = time.time() + min(max(seconds, 1.0), 6.0)
        while time.time() < end:
            try:
                data, addr = sock.recvfrom(65535)
            except socket.timeout:
                continue
            txt = data.decode(errors="ignore")
            maker = None
            m = re.search(r"onvif://www\.onvif\.org/(?:name|hardware)/([^\s<]+)", txt)
            if m:
                maker = m.group(1).replace("%20", " ")
            xaddr = re.search(r"XAddrs>([^<]+)<", txt)
            found[addr[0]] = {"ip": addr[0], "maker": maker, "xaddr": xaddr.group(1).split()[0] if xaddr else None}
    except OSError as e:
        return {"cameras": [], "error": f"discovery not possible here: {e}"}
    finally:
        sock.close()
    return {"cameras": sorted(found.values(), key=lambda x: x["ip"])}
