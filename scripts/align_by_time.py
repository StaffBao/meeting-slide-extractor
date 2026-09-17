# align_by_time.py
# Align a FULL timestamped ASR transcript to slides using VIDEO TIME (not lexical
# overlap). Each slide has meta field "t" = seconds into video when its
# representative keyframe appears. Each ASR segment has an absolute start time.
# We assign every ASR segment to the slide that was ON SCREEN at that moment
# (largest slide.t <= segment.time_sec), which is far more reliable than
# bigram overlap matching.
#
# Inputs:
#   --meta        slides_meta.json (has t + file + n)
#   --asr         output/asr_transcript.txt  (format: [HH:MM:SS,mmm] text)
#   --ocr         output/slides_ocr.txt
#   --sections    output/sections.json (optional; from build_sections.py)
# Outputs:
#   updates slides_meta.json "notes" field
#   output/slides.pptx                 (clean deck: images only)
#   output/slides_viewer.html          (ONE self-contained file by default)
#   output/transcript_by_speaker.docx  (formatted Word transcript grouped by speaker)
#   output/transcript_from_slides.md   (diagnostic per-slide OCR/notes comparison)
import argparse, json, os, re, bisect
from build_notes_ppt import (load_meta, save_meta, parse_ocr, load_sections,
                             build_markdown, build_transcript_docx,
                             build_clean_pptx, build_html)

ASR_TS = re.compile(r"^\[(\d{1,2}):(\d{2}):(\d{2}),(\d{3})\]\s*(.*)$")


def parse_asr(path):
    """Parse [HH:MM:SS,mmm] text lines -> list of {time_sec, text}."""
    segs = []
    if not os.path.exists(path):
        return segs
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            m = ASR_TS.match(line)
            if not m:
                continue
            h, mi, s, ms = (int(m.group(i)) for i in (1, 2, 3, 4))
            t = h * 3600 + mi * 60 + s + ms / 1000.0
            text = m.group(5).strip()
            if text:
                segs.append({"time_sec": t, "text": text})
    return segs


def align_by_time(meta, segments):
    """Assign each segment to the slide on screen at segment.time_sec."""
    slides = sorted(meta, key=lambda s: s.get("t", 0))
    t_list = [s.get("t", 0) for s in slides]
    notes = {s["n"]: [] for s in slides}

    unassigned = 0
    for seg in segments:
        ts = seg["time_sec"]
        # largest slide.t <= ts
        idx = bisect.bisect_right(t_list, ts) - 1
        if idx < 0:
            idx = 0  # speech before first slide -> attach to slide 1
        n = slides[idx]["n"]
        notes[n].append(seg["text"])

    for n in notes:
        # ASR engines segment very differently: small Whisper models may emit
        # hundreds of sentence fragments while larger models may emit 30-second
        # chunks. Merge both into readable Word/HTML paragraphs instead of one
        # giant wall of text or hundreds of one-line paragraphs.
        paragraphs = []
        current = ""
        for chunk in notes[n]:
            chunk = chunk.strip().replace(",", "，")
            if not chunk:
                continue
            current += chunk
            if len(current) >= 280:
                current = current.rstrip("，")
                if current and current[-1] not in "。！？?!":
                    current += "。"
                paragraphs.append(current)
                current = ""
        if current:
            current = current.rstrip("，")
            if current and current[-1] not in "。！？?!":
                current += "。"
            paragraphs.append(current)
        notes[n] = "\n\n".join(paragraphs).strip()
    assigned = sum(1 for n in notes if notes[n])
    return notes, assigned, len(notes)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta", default="slides_meta.json")
    ap.add_argument("--asr", default="output/asr_transcript.txt")
    ap.add_argument("--ocr", default="output/slides_ocr.txt")
    ap.add_argument("--outdir", default="output")
    ap.add_argument("--sections", default=None,
                    help="output/sections.json from build_sections.py — adds the "
                         "【新增节】 markers to the HTML and the transcript")
    ap.add_argument("--separate-images", action="store_true",
                    help="write slide images to <outdir>/slides/ instead of inlining "
                         "(default: ONE self-contained HTML, safe to share)")
    args = ap.parse_args()

    meta = load_meta(args.meta)
    ocr_by_slide = parse_ocr(args.ocr)
    secs = load_sections(args.sections)
    segments = parse_asr(args.asr)
    print(f"Parsed {len(segments)} ASR segments.")
    if secs:
        print("Sections: " + " / ".join("%d:%s" % (s["idx"], s["title"]) for s in secs))

    notes_by_slide, assigned, total = align_by_time(meta, segments)
    print(f"ASR segments assigned across {assigned}/{total} slides.")

    for s in meta:
        s["notes"] = notes_by_slide.get(s["n"], "")

    os.makedirs(args.outdir, exist_ok=True)
    save_meta(args.meta, meta)

    md = build_markdown(meta, ocr_by_slide,
                        os.path.join(args.outdir, "transcript_from_slides.md"),
                        sections=secs)
    tr = build_transcript_docx(meta, os.path.join(args.outdir, "transcript_by_speaker.docx"),
                               sections=secs, title="逐字稿 按讲者分节")
    clean_pptx = build_clean_pptx(meta, os.path.join(args.outdir, "slides.pptx"),
                                 sections=secs)
    viewer = build_html(meta, os.path.join(args.outdir, "slides_viewer.html"),
                        title="幻灯片与讲稿",
                        inline_images=not args.separate_images,
                        sections=secs)
    print(f"逐字稿     -> {tr}")
    print(f"自查对照   -> {md}")
    print(f"Slides PPTX-> {clean_pptx}")
    print(f"Viewer HTML-> {viewer}")


if __name__ == "__main__":
    main()
