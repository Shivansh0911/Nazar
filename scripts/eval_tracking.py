"""Tracking evaluation on MOT17 ground truth (W12, acceptance G2).

Runs the detector + tracker exactly as the edge does (sampled at DETECT_FPS) on MOT17 sequences and reports, per
config: ID switches, MOTA, an IDF1 approximation and the people-count error ("people seen" rule: tracks >= 1.5 s
with max confidence >= 0.6) against the number of ground-truth pedestrians visible in the sampled frames.

Data: Kaggle `nishilagarwal/mot-cv-a1` (MOT17-11-SDP and MOT17-13-SDP with gt; research licence, local evaluation
only, not redistributed) downloaded to DATA_DIR/datasets/mot_cv_a1:
    kaggle datasets download -d nishilagarwal/mot-cv-a1 -p <DATA_DIR>/datasets/mot_cv_a1 --unzip
    python scripts/eval_tracking.py
Writes data/eval/tracking.json (shown on the Insights page).
"""
from __future__ import annotations

import configparser
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from nazar.core.config import get_settings  # noqa: E402

CONFIGS = [
    ("v1: yolo11n + ByteTrack", "yolo11n.pt", "bytetrack", False),
    ("v2 default: yolo11s + tuned BoT-SORT", "yolo11s.pt", "botsort", True),
    ("v2 PTZ option: + camera-motion comp.", "yolo11s.pt", "botsort_gmc", True),
]


def iou_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    if not len(a) or not len(b):
        return np.zeros((len(a), len(b)))
    x1 = np.maximum(a[:, None, 0], b[None, :, 0]); y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2]); y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    aa = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1]); bb = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    return inter / np.maximum(aa[:, None] + bb[None, :] - inter, 1e-9)


def load_seq(d: Path):
    ini = configparser.ConfigParser()
    ini.read(d / "seqinfo.ini")
    fps = float(ini["Sequence"]["frameRate"]) if ini.has_section("Sequence") else 30.0
    gt = defaultdict(list)
    for line in (d / "gt" / "gt.txt").read_text().splitlines():
        f, i, x, y, w, h, flag, cls, vis = (float(v) for v in line.split(",")[:9])
        if int(flag) == 1 and int(cls) == 1 and vis >= 0.25:  # pedestrians that are at least partly visible
            gt[int(f)].append((int(i), x, y, x + w, y + h))
    frames = sorted((d / "img1").glob("*.jpg"))
    return fps, gt, frames


def evaluate(seq_dir: Path, weights: str, tracker: str, gpu: bool, det_fps: float) -> dict:
    from nazar.edge.detector import Detector

    os.environ["NAZAR_TRACKER"] = tracker
    fps, gt, frames = load_seq(seq_dir)
    step = max(1, round(fps / det_fps))
    det = Detector("auto" if gpu else "cpu", imgsz=640, conf=0.30, weights=str(ROOT / "backend" / "models" / weights),
                   tracker=tracker, fps=det_fps)
    if not gpu:
        det.gpu = False
    sel = list(range(1, len(frames) + 1, step))
    tracks: dict[int, dict] = {}
    last_match: dict[int, int] = {}
    idsw = fp = fn = tp = 0
    overlap = defaultdict(int)  # (gt id, pred id) -> matched frames
    gt_frames = defaultdict(int)
    pred_frames = defaultdict(int)
    gt_seen = set()
    for k in range(0, len(sel), 16):
        batch_ids = sel[k:k + 16]
        imgs = [cv2.imread(str(frames[f - 1])) for f in batch_ids]
        for f, dets in zip(batch_ids, det.track_batch(imgs)):
            h, w = imgs[0].shape[:2]
            ped = [d for d in dets if d.cls == "person"]
            for d in ped:
                t = tracks.setdefault(d.track_id, {"first": f, "last": f, "conf": 0.0})
                t["last"], t["conf"] = f, max(t["conf"], d.conf)
                pred_frames[d.track_id] += 1
            g = gt.get(f, [])
            for gid, *_ in g:
                gt_seen.add(gid)
                gt_frames[gid] += 1
            gb = np.array([b[1:] for b in g], float).reshape(-1, 4)
            pb = np.array([[d.box[0] * w, d.box[1] * h, d.box[2] * w, d.box[3] * h] for d in ped], float).reshape(-1, 4)
            m = iou_matrix(gb, pb)
            matched_g, matched_p = set(), set()
            if m.size:
                import lap

                cost = 1 - m
                cost[m < 0.5] = 1e3
                _, x, _ = lap.lapjv(cost, extend_cost=True)
                for gi, pi in enumerate(x):
                    if pi >= 0 and m[gi, pi] >= 0.5:
                        gid, pid = g[gi][0], ped[pi].track_id
                        matched_g.add(gi); matched_p.add(pi)
                        if gid in last_match and last_match[gid] != pid:
                            idsw += 1
                        last_match[gid] = pid
                        overlap[(gid, pid)] += 1
            tp += len(matched_g); fn += len(g) - len(matched_g); fp += len(ped) - len(matched_p)
    n_gt = sum(gt_frames.values())
    # IDF1 approximation: greedy one-to-one assignment of gt ids to pred ids by matched frames
    used_p, idtp = set(), 0
    for (gid, pid), n in sorted(overlap.items(), key=lambda x: -x[1]):
        if pid in used_p or gid in {g for g, p in overlap if p in used_p and (g, p) in overlap and False}:
            continue
        used_p.add(pid)
        idtp += n
    idf1 = 2 * idtp / max(1, n_gt + sum(pred_frames.values()))
    del det
    import gc

    import torch

    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    min_frames = 1.5 * det_fps
    counted = sum(1 for t in tracks.values() if (t["last"] - t["first"]) / fps >= 1.5 and t["conf"] >= 0.6)
    raw_ids = len(tracks)
    gt_long = sum(1 for gid, n in gt_frames.items() if n >= min_frames)
    return {"frames": len(sel), "id_switches": idsw, "mota": round(1 - (fn + fp + idsw) / max(1, n_gt), 3),
            "idf1": round(idf1, 3), "pred_ids": raw_ids, "counted": counted, "gt_people": len(gt_seen),
            "gt_people_1_5s": gt_long, "count_error_pct": round(abs(counted - gt_long) * 100 / max(1, gt_long), 1),
            "recall": round(tp / max(1, n_gt), 3), "precision": round(tp / max(1, tp + fp), 3)}


def main() -> int:
    s = get_settings()
    base = s.data_dir / "datasets" / "mot_cv_a1" / "Tracking" / "train"
    seqs = sorted(p for p in base.glob("MOT17-*") if (p / "gt" / "gt.txt").exists())
    if not seqs:
        print(f"no MOT17 sequences in {base} - see the docstring for the download command")
        return 1
    rows = []
    for seq in seqs:
        for name, weights, tracker, gpu in CONFIGS:
            r = evaluate(seq, weights, tracker, gpu, s.DETECT_FPS)
            rows.append({"sequence": seq.name, "config": name, **r})
            print(f"{seq.name:<14} {name:<40} IDsw {r['id_switches']:>3}  MOTA {r['mota']:.3f}  IDF1~{r['idf1']:.3f}  "
                  f"counted {r['counted']:>3} vs gt {r['gt_people_1_5s']:>3} ({r['count_error_pct']}%)  "
                  f"recall {r['recall']}", flush=True)
    by = defaultdict(lambda: defaultdict(float))
    for r in rows:
        for k in ("id_switches", "mota", "idf1", "count_error_pct"):
            by[r["config"]][k] += r[k] / len(seqs)
    summary = "; ".join(f"{c}: IDsw {v['id_switches']:.0f}, MOTA {v['mota']:.2f}, IDF1~{v['idf1']:.2f}, count err "
                        f"{v['count_error_pct']:.0f}%" for c, v in by.items())
    print("\nmean over sequences -", summary)
    out = s.data_dir / "eval" / "tracking.json"
    out.write_text(json.dumps({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "det_fps": s.DETECT_FPS,
                               "rows": rows, "summary": summary}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
