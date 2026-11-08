"""M0 benchmark: can RF-DETR Nano + ByteTrack find and follow players on CPU, fast enough?

    uv run python run.py --video ~/vg-footage/test-session.mp4 --out out/plain
    uv run python run.py --video ~/vg-footage/test-session.mp4 --tile-far-half --out out/tiled

Writes out/metrics.json, out/annotated.mp4 (first 60 s) and out/frames/ (10 evenly spaced
annotated frames for hand-checking). See RESULTS.md for how to turn this into a verdict.
"""
import argparse
import json
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path

TARGET_CLASSES = ("person", "sports ball")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--video", required=True, type=Path)
    p.add_argument("--sample-fps", type=float, default=10.0)
    p.add_argument("--seconds", type=float, default=300.0, help="how much of the video to process")
    p.add_argument("--tile-far-half", action="store_true",
                   help="also detect on the top half upscaled 2x (distant players), merged with NMS")
    p.add_argument("--threshold", type=float, default=0.3)
    p.add_argument("--out", type=Path, default=Path("out"))
    return p.parse_args()


def main() -> None:
    args = parse_args()
    # Heavy imports here so --help works without the ML stack.
    import cv2
    import numpy as np
    import supervision as sv
    from rfdetr import RFDETRNano
    from rfdetr.util.coco_classes import COCO_CLASSES

    wanted = {cid for cid, name in COCO_CLASSES.items() if name in TARGET_CLASSES}
    ball_ids = {cid for cid, name in COCO_CLASSES.items() if name == "sports ball"}
    if len(wanted) != len(TARGET_CLASSES):
        raise SystemExit(f"class lookup failed: {wanted}")

    cap = cv2.VideoCapture(str(args.video.expanduser()))
    if not cap.isOpened():
        raise SystemExit(f"cannot open {args.video}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_src = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, round(src_fps / args.sample_fps))
    eff_fps = src_fps / step
    max_src = min(total_src, int(args.seconds * src_fps))
    n_samples = max_src // step
    keep_frames = set(np.linspace(0, max(n_samples - 1, 0), 10, dtype=int).tolist())

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "frames").mkdir(exist_ok=True)
    writer = cv2.VideoWriter(str(args.out / "annotated.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), eff_fps,
                             (width, height))

    model = RFDETRNano()
    tracker = sv.ByteTrack(frame_rate=round(eff_fps))
    boxes, labels = sv.BoxAnnotator(thickness=2), sv.LabelAnnotator(text_scale=0.4, text_padding=2)

    def detect(rgb):
        d = model.predict(rgb, threshold=args.threshold)
        return d[np.isin(d.class_id, list(wanted))]

    def detect_tiled(rgb):
        full = detect(rgb)
        top = rgb[: height // 2]
        up = cv2.resize(top, (width * 2, (height // 2) * 2), interpolation=cv2.INTER_CUBIC)
        far = detect(up)
        far.xyxy = far.xyxy / 2.0  # back to full-frame coordinates (crop starts at y=0)
        return sv.Detections.merge([full, far]).with_nms(threshold=0.5, class_agnostic=False)

    ms, persons_per_frame, ball_frames = [], Counter(), 0
    track_frames: dict[int, int] = defaultdict(int)
    sample_idx = src_idx = 0
    print(f"{args.video.name}: {width}x{height} @ {src_fps:.1f} fps, sampling every {step} frames "
          f"({eff_fps:.1f} fps), {n_samples} samples, tiling={'on' if args.tile_far_half else 'off'}")

    while src_idx < max_src:
        ok, bgr = cap.read()
        if not ok:
            break
        if src_idx % step:
            src_idx += 1
            continue
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        t0 = time.perf_counter()
        dets = detect_tiled(rgb) if args.tile_far_half else detect(rgb)
        ms.append((time.perf_counter() - t0) * 1000)

        is_ball = np.isin(dets.class_id, list(ball_ids))
        people = tracker.update_with_detections(dets[~is_ball])
        persons_per_frame[len(people)] += 1
        ball_frames += int(is_ball.any())
        for tid in people.tracker_id:
            track_frames[int(tid)] += 1

        if sample_idx / eff_fps < 60 or sample_idx in keep_frames:
            frame = boxes.annotate(bgr.copy(), people)
            frame = labels.annotate(frame, people, labels=[f"#{t}" for t in people.tracker_id])
            if dets[is_ball].xyxy.size:
                frame = sv.BoxAnnotator(color=sv.Color.YELLOW).annotate(frame, dets[is_ball])
            if sample_idx / eff_fps < 60:
                writer.write(frame)
            if sample_idx in keep_frames:
                cv2.imwrite(str(args.out / "frames" / f"frame_{sample_idx:05d}.jpg"), frame)
        sample_idx += 1
        src_idx += 1
        if sample_idx % 50 == 0:
            print(f"  {sample_idx}/{n_samples} samples, {statistics.mean(ms):.0f} ms/frame")

    writer.release()
    cap.release()
    if not ms:
        raise SystemExit("no frames processed")
    lengths_s = sorted(n / eff_fps for n in track_frames.values())
    metrics = {
        "video": str(args.video),
        "resolution": f"{width}x{height}",
        "sample_fps": round(eff_fps, 2),
        "frames_processed": len(ms),
        "tiling": args.tile_far_half,
        "ms_per_frame_mean": round(statistics.mean(ms), 1),
        "ms_per_frame_p95": round(sorted(ms)[int(0.95 * (len(ms) - 1))], 1),
        "persons_per_frame": dict(sorted(persons_per_frame.items())),
        "tracks_total": len(track_frames),
        "track_length_median_s": round(statistics.median(lengths_s), 1) if lengths_s else 0,
        "ball_detected_frame_ratio": round(ball_frames / len(ms), 3),
        "projected_hours_for_90_min": round(statistics.mean(ms) / 1000 * eff_fps * 90 * 60 / 3600, 2),
    }
    (args.out / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
