# punctuate_notes.py
# Punctuate & paragraph the per-slide transcript (already aligned by time in
# slides_meta.json "notes" field) using a OpenAI-compatible LLM. Each slide's
# raw joined speech becomes one natural punctuated block (1-2 paragraphs).
# Then rebuild slides.pptx, slides_viewer.html, and transcript_by_speaker.docx;
# diagnostic legacy text/Markdown files are also refreshed.
import argparse, json, os, re, sys, time, urllib.request
from build_notes_ppt import (load_meta, save_meta, parse_ocr, load_sections,
                             build_markdown, build_transcript_docx,
                             build_clean_pptx, build_html)

PROMPT = (
    "你是一名严谨的中文会议转录校对员。下面是一段会议发言的语音识别（ASR）文本，"
    "缺少标点、可能有同音错别字，且由若干短句拼接而成。请：\n"
    "1. 添加正确的中文标点（逗号、句号、问号、叹号、顿号、引号、冒号等），按语义合并成通顺的自然句子；\n"
    "2. 仅在不改变原意的前提下，修正上下文明显是同音或近音识别错误的字词（例如结合语境明显错误的词，如'少点建设'应为'哨点建设'、'市卫监委'应为'市卫健委'）；\n"
    "3. 保持原话内容与口语风格，保留必要的语气词，不要增删实质信息，不要书面化改写，不要添加任何解释或序号；\n"
    "4. 若文本较长（明显超过约150字）且内部存在清晰的话题转换，可酌情分为2段，否则保持为一段；段落之间用空行分隔。\n"
    "只输出校对后的文本。"
)


def fmt_mmss(sec):
    """mm:ss, or h:mm:ss once the recording passes an hour (training recordings
    routinely run for hours, and "158:34" reads as a broken minute field)."""
    if sec is None:
        return "00:00"
    sec = max(0.0, float(sec))
    h, m, s = int(sec // 3600), int((sec % 3600) // 60), int(sec % 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def call_llm(url, api_key, model, text):
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": text},
        ],
        "temperature": 0.1,
        "max_tokens": 4096,
        "enable_thinking": False,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                resp = json.loads(r.read().decode("utf-8"))
            return resp["choices"][0]["message"]["content"].strip()
        except Exception as e:
            last = e
            if attempt == 3:
                break
            time.sleep(3 * (attempt + 1))
    raise last if last else RuntimeError("llm call failed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta", default="slides_meta.json")
    ap.add_argument("--ocr", default="output/slides_ocr.txt")
    ap.add_argument("--outdir", default="output")
    ap.add_argument("--url", required=True)
    ap.add_argument("--api-key", required=True)
    ap.add_argument("--model", default="qwen3.7-max")
    ap.add_argument("--limit", type=int, default=0, help="only first N slides (0=all)")
    ap.add_argument("--sections", default=None,
                    help="output/sections.json from build_sections.py — adds the "
                         "【新增节】 markers to the HTML and the transcripts")
    ap.add_argument("--separate-images", action="store_true",
                    help="write slide images to <outdir>/slides/ instead of inlining "
                         "(default: ONE self-contained HTML, safe to share)")
    args = ap.parse_args()

    meta = load_meta(args.meta)
    secs = load_sections(args.sections)
    if args.limit:
        meta = [s for s in meta if s.get("notes")][:args.limit]
    total = len(meta)
    done = 0
    for s in meta:
        raw = s.get("notes", "").strip()
        if not raw:
            continue
        try:
            s["notes"] = call_llm(args.url, args.api_key, args.model, raw)
        except Exception as e:
            print(f"  [FAIL slide {s.get('n')}] keep raw: {e}", file=sys.stderr, flush=True)
        done += 1
        if done % 20 == 0:
            print(f"  progress {done}/{total}", flush=True)

    save_meta(args.meta, meta)

    ocr_by_slide = parse_ocr(args.ocr)
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

    # paragraphed transcript.txt — carries the same 【新增节】 markers
    meta_all = load_meta(args.meta)
    meta_all = sorted(meta_all, key=lambda x: x.get("t", 0))
    by_from = {s["from_n"]: s for s in secs}
    lines = ["# 培训转写稿（按幻灯片时间整理，已加标点）\n", "\n"]
    for s in meta_all:
        n = s.get("n")
        t = s.get("t", 0)
        sec = by_from.get(n)
        if sec:
            lines.append("\n【新增节 %d】%s（第 %d–%d 页）\n\n"
                         % (sec["idx"], sec["title"], sec["from_n"], sec["to_n"]))
        note = s.get("notes", "").strip()
        if not note:
            continue
        lines.append(f"（{fmt_mmss(t)}）{note}\n\n")
    txt_path = os.path.join(args.outdir, "transcript.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("".join(lines))

    print(f"逐字稿     -> {tr}")
    print(f"自查对照   -> {md}")
    print(f"Slides PPTX-> {clean_pptx}")
    print(f"Viewer HTML-> {viewer}")
    print(f"Transcript -> {txt_path}")


if __name__ == "__main__":
    main()
