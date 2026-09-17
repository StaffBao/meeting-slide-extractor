# extract_keyframes.py
# Fast slide extraction: dump I-frames (keyframes) via ffmpeg (no full decode),
# then dedup consecutive similar keyframes with phash, save representatives.
import argparse, os, sys, subprocess, json, shutil
import cv2, numpy as np


def imread_unicode(path):
    """Read an image from a path that may contain non-ASCII characters."""
    try:
        data = np.fromfile(path, dtype=np.uint8)
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except (OSError, ValueError):
        return None


def imwrite_unicode(path, image):
    """Write an image to a path that may contain non-ASCII characters."""
    ext = os.path.splitext(path)[1] or ".png"
    ok, encoded = cv2.imencode(ext, image)
    if not ok:
        return False
    try:
        encoded.tofile(path)
        return True
    except OSError:
        return False

def find_ffmpeg(explicit=None):
    """Locate an ffmpeg executable at runtime; no machine-specific paths hardcoded.
    Order: explicit --ffmpeg arg -> imageio_ffmpeg bundle -> system PATH ->
    MEETING_FFMPEG env var. Raises FileNotFoundError with guidance if all fail.
    """
    if explicit and os.path.isfile(explicit):
        return explicit
    try:
        import imageio_ffmpeg
        p = imageio_ffmpeg.get_ffmpeg_exe()
        if p and os.path.isfile(p):
            return p
    except Exception:
        pass
    p = shutil.which("ffmpeg")
    if p:
        return p
    p = os.environ.get("MEETING_FFMPEG")
    if p and os.path.isfile(p):
        return p
    raise FileNotFoundError(
        "ffmpeg not found. Either `pip install imageio-ffmpeg`, put ffmpeg on PATH, "
        "set the MEETING_FFMPEG environment variable, or pass --ffmpeg <path>."
    )

def phash(gray, size=32, hlen=8):
    small = cv2.resize(gray, (size, size), interpolation=cv2.INTER_AREA)
    dct = cv2.dct(small.astype(np.float32))
    top = dct[:hlen, :hlen]
    med = np.median(top)
    return (top > med).flatten()

def hamming(a, b):
    return int(np.count_nonzero(a != b))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ffmpeg", default=None,
                    help="optional; auto-detected (imageio_ffmpeg -> PATH -> MEETING_FFMPEG env)")
    ap.add_argument("--video", required=True)
    ap.add_argument("--images-dir", required=True)
    ap.add_argument("--tmp-dir", required=True)
    ap.add_argument("--threshold", type=int, default=10)
    ap.add_argument("--dark-thresh", type=float, default=20)
    args = ap.parse_args()

    FF = find_ffmpeg(args.ffmpeg)
    cap = cv2.VideoCapture(args.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    cap.release()

    os.makedirs(args.tmp_dir, exist_ok=True)
    os.makedirs(args.images_dir, exist_ok=True)

    print(f"[1/3] dumping keyframes (fps={fps:.2f}) ...")
    subprocess.run([FF, "-hide_banner", "-loglevel", "error",
                    "-skip_frame", "nokey", "-i", args.video,
                    "-vsync", "vfr", "-frame_pts", "1", "-an",
                    os.path.join(args.tmp_dir, "kf_%010d.png")],
                   check=True)
    files = sorted(f for f in os.listdir(args.tmp_dir) if f.endswith(".png"))
    print(f"      keyframes found: {len(files)}")

    print("[2/3] phash dedup ...")
    current = None
    saved = []
    saved_count = 0
    for fn in files:
        path = os.path.join(args.tmp_dir, fn)
        img = imread_unicode(path)
        if img is None:
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        bright = float(np.mean(gray))
        if bright < args.dark_thresh:
            continue
        h = phash(gray)
        pts = int(fn.split("_")[1].split(".")[0])
        t = round(pts / fps, 1)
        if current is None:
            saved_count += 1
            out = os.path.join(args.images_dir, f"slide_{saved_count:03d}.png")
            if not imwrite_unicode(out, img):
                raise OSError("failed to write image: %s" % out)
            saved.append({"n": saved_count, "file": out, "_h": h, "pts": pts, "t": t, "bright": round(bright,1)})
            current = h
            continue
        if hamming(h, current) <= args.threshold:
            continue
        # differs -> check not duplicate of an earlier saved slide
        dup = any(hamming(h, s["_h"]) <= 2 for s in saved)
        if dup:
            current = h
            continue
        saved_count += 1
        out = os.path.join(args.images_dir, f"slide_{saved_count:03d}.png")
        if not imwrite_unicode(out, img):
            raise OSError("failed to write image: %s" % out)
        saved.append({"n": saved_count, "file": out, "_h": h, "pts": pts, "t": t, "bright": round(bright,1)})
        print(f"  + slide {saved_count:03d} @ {t}s")
        current = h

    print("[3/3] writing meta ...")
    meta = [{k: v for k, v in s.items() if k != "_h"} for s in saved]
    meta_path = os.path.join(os.path.dirname(args.images_dir), "slides_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"DONE: {saved_count} slides -> {meta_path}")

if __name__ == "__main__":
    main()
