# ocr_slides.py
# Run Chinese OCR (RapidOCR) over each extracted slide image and write a
# plain-text transcript (slides_ocr.txt) with one section per slide.
import argparse, json, os

try:
    from rapidocr import RapidOCR
except ImportError:
    from rapidocr_onnxruntime import RapidOCR


def ocr_texts(engine, image_path):
    """Return (texts, elapsed_seconds) for RapidOCR 1.x and 3.x APIs."""
    out = engine(image_path)
    if hasattr(out, "txts"):
        return list(out.txts or []), float(out.elapse or 0)
    result, elapsed = out
    texts = [item[1] for item in (result or []) if len(item) > 1]
    # Legacy rapidocr-onnxruntime may return a list of stage timings.
    if isinstance(elapsed, (int, float)):
        seconds = float(elapsed)
    elif isinstance(elapsed, (list, tuple)):
        seconds = sum(float(item) for item in elapsed
                      if isinstance(item, (int, float)))
    else:
        seconds = 0.0
    return texts, seconds

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with open(args.meta, encoding="utf-8") as f:
        meta = json.load(f)

    engine = RapidOCR()  # local ONNX models
    buf = []
    for s in meta:
        path = s["file"]
        try:
            lines, elapse = ocr_texts(engine, path)
        except Exception as e:
            lines = []
            elapse = 0
            buf.append(f"# 第 {s['n']:03d} 页 (录像 {s['t']}s) — OCR 失败: {e}\n")
            print(f"  slide {s['n']:03d}: OCR failed {e}")
            continue
        text = "\n".join(lines).strip()
        buf.append(f"# 第 {s['n']:03d} 页 (录像 {s['t']}s)\n{text}\n")
        print(f"  slide {s['n']:03d}: {len(lines)} lines, {elapse:.2f}s")

    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(buf))
    print(f"OCR done -> {args.out}  ({len(meta)} slides)")

if __name__ == "__main__":
    main()
