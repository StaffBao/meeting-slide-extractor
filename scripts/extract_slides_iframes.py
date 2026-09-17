# extract_slides_iframes.py
# Re-extract clean slides from an already-dumped I-frame directory (kf_all/).
# Algorithm:
#   1. pHash every I-frame; segment ordered frames into runs (Hamming <= thresh).
#   2. Keep only runs with length >= run_min_len (stable content). Singleton runs
#      (fades / flashes / transient UI) are rejected into review/.
#   3. Within each kept run pick the representative frame whose hash is closest to
#      the run's majority hash (avoids taking the leading/trailing fade frame).
#   4. Content filters: too dark, too flat, global duplicate, UI-keyword OCR.
#   5. Crop pure/near-black borders, save to images/, write slides_meta.json.
import argparse, os, json, sys, shutil
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


def rapidocr_texts(engine, image_path):
    """Return OCR texts for both RapidOCR's legacy and current APIs."""
    out = engine(image_path)
    if hasattr(out, "txts"):
        return list(out.txts or [])
    result, _elapsed = out
    return [item[1] for item in (result or []) if len(item) > 1]

UI_KEYWORDS = [
    # WPS editing chrome
    "WPS Office", "WPS AI", "稻壳", "会员专享",
    # 顶部/左侧菜单栏高频词，连续出现多组才认为是编辑视图
    "开始", "插入", "设计", "切换", "动画", "放映", "审阅", "视图", "工具",
    # 腾讯会议等待/主页 UI
    "腾讯会议", "快速会议", "等待中", "会议号:", "加入会议", "发起会议",
    # 录屏水印
    "的屏幕共享",
    # macOS 桌面 / 播放器 / 其他应用窗口
    "QuickTime Player", "Finder", "文件", "编辑", "显示", "窗口", "帮助",
    "豆包", "微信", "未读消息", "未读", "菜单栏",
]

def ui_score(text):
    """Count how many distinct UI keyword groups appear in OCR text.
    Returns >=2 only when several chrome words co-occur, so that a single
    coincidental hit (e.g. a slide that literally says '开始') is not rejected."""
    return len(set(kw for kw in UI_KEYWORDS if kw in text))

def phash(gray, size=32, hlen=8):
    small = cv2.resize(gray, (size, size), interpolation=cv2.INTER_AREA)
    dct = cv2.dct(small.astype(np.float32))
    top = dct[:hlen, :hlen]
    med = np.median(top)
    return (top > med).flatten()

def hamming(a, b):
    return int(np.count_nonzero(a != b))

def crop_black_borders(img, border_thresh=10, max_border=0.18):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    H, W = g.shape
    row = g.mean(axis=1)
    col = g.mean(axis=0)
    content = row[row > border_thresh]
    content_mean = float(content.mean()) if len(content) else float(row.mean())
    def is_black(v):
        return v < border_thresh or (content_mean > 0 and v < 0.20 * content_mean and v < 48)
    t = 0
    while t < H and is_black(row[t]):
        t += 1
    b = H - 1
    while b > t and is_black(row[b]):
        b -= 1
    l = 0
    while l < W and is_black(col[l]):
        l += 1
    r = W - 1
    while r > l and is_black(col[r]):
        r -= 1
    max_t = int(H * max_border); max_b = int(H * max_border)
    max_l = int(W * max_border); max_r = int(W * max_border)
    t = min(t, max_t); b = max(b, H - 1 - max_b)
    l = min(l, max_l); r = max(r, W - 1 - max_r)
    if b <= t or r <= l:
        return img
    # only crop if something actually changed
    if t == 0 and b == H - 1 and l == 0 and r == W - 1:
        return img
    return img[t:b + 1, l:r + 1]

def majority_hash(hashes):
    arr = np.array(hashes)  # (n, bits)
    return (arr.mean(axis=0) >= 0.5)

def choose_representative(run):
    hashes = [r["hash"] for r in run]
    center = majority_hash(hashes)
    best = min(run, key=lambda r: hamming(r["hash"], center))
    return best

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keyframes-dir", required=True)
    ap.add_argument("--images-dir", required=True)
    ap.add_argument("--video", default=None, help="only used to read fps for timestamps")
    ap.add_argument("--phash-thresh", type=int, default=10)
    ap.add_argument("--run-min-len", type=int, default=2)
    ap.add_argument("--dark-thresh", type=float, default=20.0)
    ap.add_argument("--contrast-min", type=float, default=5.0)
    ap.add_argument("--border-thresh", type=float, default=10.0)
    ap.add_argument("--max-border", type=float, default=0.18)
    ap.add_argument("--filter-ui", action="store_true", default=True)
    ap.add_argument("--no-filter-ui", dest="filter_ui", action="store_false")
    ap.add_argument("--calibrate-sec", type=float, default=None)
    ap.add_argument("--review-dir", default="review")
    args = ap.parse_args()

    fps = 30.0
    if args.video:
        cap = cv2.VideoCapture(args.video)
        f = cap.get(cv2.CAP_PROP_FPS)
        if f:
            fps = f
        cap.release()

    kf_dir = args.keyframes_dir
    files = sorted(f for f in os.listdir(kf_dir) if f.endswith(".png"))
    print(f"[1/4] reading {len(files)} I-frames ...")

    frames = []
    for fn in files:
        path = os.path.join(kf_dir, fn)
        img = imread_unicode(path)
        if img is None:
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        try:
            pts = int(fn.split("_")[1].split(".")[0])
        except Exception:
            pts = len(frames)
        frames.append({
            "fn": fn, "path": path, "pts": pts,
            "hash": phash(gray),
            "bright": float(np.mean(gray)),
            "contrast": float(np.std(gray)),
        })
    frames.sort(key=lambda x: x["pts"])
    if args.calibrate_sec:
        lim = args.calibrate_sec * fps
        frames = [f for f in frames if f["pts"] <= lim]
        print(f"      calibration mode: {len(frames)} frames (<= {args.calibrate_sec}s)")

    # segment into runs
    print("[2/4] segmenting runs ...")
    runs = []
    cur = [frames[0]] if frames else []
    for f in frames[1:]:
        if hamming(f["hash"], cur[-1]["hash"]) <= args.phash_thresh:
            cur.append(f)
        else:
            runs.append(cur)
            cur = [f]
    if cur:
        runs.append(cur)

    # group runs into kept (>=run_min_len) and rejected singletons
    kept_runs = [r for r in runs if len(r) >= args.run_min_len]
    rejected = [f for r in runs if len(r) < args.run_min_len for f in r]
    print(f"      total runs={len(runs)} kept_runs={len(kept_runs)} rejected_singletons={len(rejected)}")

    os.makedirs(args.images_dir, exist_ok=True)
    os.makedirs(args.review_dir, exist_ok=True)
    for f in os.listdir(args.review_dir):
        try:
            os.remove(os.path.join(args.review_dir, f))
        except Exception:
            pass

    saved = []
    saved_count = 0
    rejected_meta = []

    # optional OCR engine for UI detection
    ocr_engine = None
    if args.filter_ui:
        try:
            try:
                from rapidocr import RapidOCR
            except ImportError:
                from rapidocr_onnxruntime import RapidOCR
            ocr_engine = RapidOCR()
        except Exception as e:
            print(f"      [warn] RapidOCR unavailable for UI filter: {e}")
            ocr_engine = None

    print("[3/4] selecting representatives + filters ...")
    for run in kept_runs:
        rep = choose_representative(run)
        reason = None
        if rep["bright"] < args.dark_thresh:
            reason = f"too_dark(bright={rep['bright']:.1f})"
        elif rep["contrast"] < args.contrast_min:
            reason = f"too_flat(contrast={rep['contrast']:.1f})"
        else:
            dup = any(hamming(rep["hash"], s["_h"]) <= 2 for s in saved)
            if dup:
                reason = "duplicate"
            elif ocr_engine is not None:
                try:
                    txt = " ".join(rapidocr_texts(ocr_engine, rep["path"]))
                    score = ui_score(txt)
                    if score >= 2:
                        reason = f"ui_keyword({score})"
                except Exception:
                    pass
        if reason:
            # copy to review with reason
            dst = os.path.join(args.review_dir, f"rej_{rep['fn']}")
            try:
                shutil.copy(rep["path"], dst)
            except Exception:
                pass
            rejected_meta.append({"fn": rep["fn"], "pts": rep["pts"],
                                  "t": round(rep["pts"] / fps, 1),
                                  "bright": round(rep["bright"], 1),
                                  "contrast": round(rep["contrast"], 1),
                                  "reason": reason})
            continue
        # accept
        img = imread_unicode(rep["path"])
        if img is None:
            rejected_meta.append({"fn": rep["fn"], "pts": rep["pts"],
                                  "t": round(rep["pts"] / fps, 1),
                                  "reason": "image_read_failed"})
            continue
        cropped = crop_black_borders(img, args.border_thresh, args.max_border)
        saved_count += 1
        out_path = os.path.join(args.images_dir, f"slide_{saved_count:03d}.png")
        if not imwrite_unicode(out_path, cropped):
            raise OSError("failed to write image: %s" % out_path)
        saved.append({"n": saved_count, "file": out_path, "_h": rep["hash"],
                      "pts": rep["pts"], "t": round(rep["pts"] / fps, 1),
                      "bright": round(rep["bright"], 1),
                      "contrast": round(rep["contrast"], 1)})
        print(f"  + slide {saved_count:03d} @ {rep['pts']/fps:.1f}s  bright={rep['bright']:.1f} size={cropped.shape[1]}x{cropped.shape[0]}")

    # also dump rejected singletons to review
    for f in rejected:
        dst = os.path.join(args.review_dir, f"rej_{f['fn']}")
        try:
            shutil.copy(f["path"], dst)
        except Exception:
            pass
        rejected_meta.append({"fn": f["fn"], "pts": f["pts"],
                              "t": round(f["pts"] / fps, 1),
                              "bright": round(f["bright"], 1),
                              "contrast": round(f["contrast"], 1),
                              "reason": "singleton_run"})

    print("[4/4] writing meta ...")
    meta = [{k: v for k, v in s.items() if k != "_h"} for s in saved]
    meta_path = os.path.join(os.path.dirname(args.images_dir.rstrip("/\\")), "slides_meta.json")
    # if images_dir is relative to project root, meta goes to project root
    if not os.path.isabs(meta_path):
        meta_path = os.path.join(os.getcwd(), "slides_meta.json")
    with open(meta_path, "w", encoding="utf-8") as fp:
        json.dump(meta, fp, ensure_ascii=False, indent=2)
    with open(os.path.join(args.review_dir, "rejected_meta.json"), "w", encoding="utf-8") as fp:
        json.dump(rejected_meta, fp, ensure_ascii=False, indent=2)
    print(f"DONE: {saved_count} slides -> {meta_path}")
    print(f"      {len(rejected_meta)} frames moved to review/ ({args.review_dir})")

if __name__ == "__main__":
    main()
