# ingest_user_transcript.py
# Mode A: the USER supplies a verbatim transcript (exported from Tencent Meeting
# or pasted). We integrate it into paragraphs and map each part to the slide that
# was on screen, then rebuild the three standard deliverables: slides.pptx,
# slides_viewer.html, and transcript_by_speaker.docx.
#
# Two input shapes are auto-detected:
#   * TIMESTAMPED  -> lines look like "[HH:MM:SS,mmm] text" / "[HH:MM:SS] text" /
#                     "[MM:SS] text" / "HH:MM:SS text". We align by VIDEO TIME
#                     (reuse align_by_time.align_by_time, the very same logic as
#                     the ASR path) -> exact per-page mapping.
#   * PLAIN (no timestamps) -> we ask an OpenAI-compatible LLM to (a) split the
#                     transcript into punctuated paragraphs and (b) map each
#                     paragraph to a slide using the slide OCR content. Falls
#                     back to an order-based equal split if no LLM is available
#                     or the model output cannot be parsed.
#
# Inputs:
#   --meta        slides_meta.json (already extracted; carries n / file / t)
#   --transcript  user-provided transcript file (utf-8)
#   --ocr         output/slides_ocr.txt (used as mapping context in plain mode)
#   --outdir      output directory
#   --mode        auto | timestamped | content  (default auto = detect)
#   --url/--api-key/--model  LLM endpoint (only needed in plain/content mode)
import argparse, json, os, re, sys, time, urllib.request, bisect
from build_notes_ppt import (load_meta, save_meta, parse_ocr, load_sections,
                             load_name_fixes, apply_name_fixes,
                             build_markdown, build_transcript_docx,
                             build_clean_pptx, build_html)
from align_by_time import align_by_time

# Flexible timestamp patterns (most specific first).
TS_PATTERNS = [
    (re.compile(r"^\[(\d{1,2}):(\d{2}):(\d{2}),(\d{3})\]\s*(.*)$"), "hms_ms"),
    (re.compile(r"^\[(\d{1,2}):(\d{2}):(\d{2})\]\s*(.*)$"), "hms"),
    (re.compile(r"^\[(\d{1,2}):(\d{2})\]\s*(.*)$"), "ms"),
    (re.compile(r"^(\d{1,2}):(\d{2}):(\d{2})\s*[–\-:：]?\s*(.*)$"), "hms_lead"),
]


def to_sec(groups, kind):
    if kind == "hms_ms":
        h, mi, s, ms = (int(x) for x in groups)
        return h * 3600 + mi * 60 + s + ms / 1000.0
    if kind == "hms" or kind == "hms_lead":
        h, mi, s = (int(x) for x in groups)
        return h * 3600 + mi * 60 + s
    if kind == "ms":
        mi, s = (int(x) for x in groups)
        return mi * 60 + s
    return 0.0


def detect_and_parse_transcript(path):
    """Return (mode, segments) where segments is list of {time_sec,text} for
    timestamped input, or None text blob for plain input."""
    lines = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            lines.append(line.rstrip("\n"))
    ts_hits = 0
    segs = []
    for line in lines:
        if not line.strip():
            continue
        for pat, kind in TS_PATTERNS:
            m = pat.match(line)
            if m:
                g = m.groups()
                text = g[-1].strip()
                # strip a leading "发言人:" / "姓名：" speaker tag is kept in text
                if text:
                    segs.append({"time_sec": to_sec(g[:-1], kind), "text": text})
                    ts_hits += 1
                break
    total = sum(1 for l in lines if l.strip())
    if total and ts_hits / total >= 0.3:
        return "timestamped", segs
    # plain: join everything into one blob, drop obvious speaker/time prefixes
    blob = "\n".join(lines).strip()
    return "plain", blob


# ---------------------------------------------------------------------------
# Plain-mode LLM mapping
# ---------------------------------------------------------------------------
MAP_PROMPT = (
    "你是一名严谨的中文会议转录整理员。下面给出一场培训的「幻灯片内容（每页 OCR 提取的"
    "标题/要点）」以及「一份没有时间标记的讲话逐字稿」。请完成两件事：\n"
    "1. 把逐字稿按语义拆成若干段落，并加上正确的中文标点（段落之间用空行分隔）；\n"
    "2. 根据每页幻灯片的内容，把对应的段落分配给该页（一段文字可能对应一页，也可能跨多页；"
    "某页若没有对应讲话则文字留空）。\n"
    "输出严格的 JSON 数组，元素格式：{\"n\": <页号整数>, \"text\": \"<该页对应的讲稿，已加标点、"
    "已分段落；无对应内容则为空字符串>\"}。只输出 JSON，不要任何解释。\n\n"
    "幻灯片内容：\n{slides}\n\n逐字稿：\n{transcript}\n"
)


def call_llm(url, api_key, model, text):
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是一名严谨的中文会议转录整理员，只输出要求的格式。"},
            {"role": "user", "content": text},
        ],
        "temperature": 0.1,
        "max_tokens": 8192,
        "enable_thinking": False,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                resp = json.loads(r.read().decode("utf-8"))
            return resp["choices"][0]["message"]["content"].strip()
        except Exception as e:
            last = e
            if attempt == 3:
                break
            time.sleep(3 * (attempt + 1))
    raise last if last else RuntimeError("llm call failed")


def extract_json_array(text):
    s = text.find("[")
    e = text.rfind("]")
    if s == -1 or e == -1 or e <= s:
        return None
    try:
        return json.loads(text[s:e + 1])
    except Exception:
        return None


def _coerce_notes(arr):
    """Accept list-of-{n,text}, dict-of-{pagenum:text}, or a stringified form."""
    notes = {}
    if isinstance(arr, dict):
        for k, v in arr.items():
            try:
                notes[int(k)] = (v or "").strip()
            except Exception:
                pass
        return notes
    if not isinstance(arr, list):
        return notes
    for item in arr:
        if isinstance(item, dict):
            try:
                n = item.get("n")
                if n is None:
                    continue
                notes[int(n)] = (item.get("text") or "").strip()
            except Exception:
                continue
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            try:
                notes[int(item[0])] = str(item[1]).strip()
            except Exception:
                continue
    return notes


def map_by_llm(meta, transcript_blob, ocr_by_slide, url, api_key, model):
    slides_sorted = sorted(meta, key=lambda x: x.get("t", 0))
    slide_lines = []
    for s in slides_sorted:
        n = s["n"]
        ocr = ocr_by_slide.get(n, "")
        # keep first ~200 chars as a title/key hint to save tokens
        hint = ocr.replace("\n", " ")[:200]
        slide_lines.append(f"第{n}页：{hint}")
    slides_block = "\n".join(slide_lines)
    # NOTE: use .replace(), NOT .format() — MAP_PROMPT contains a literal
    # {"n": ...} JSON example whose braces would break str.format().
    prompt = MAP_PROMPT.replace("{slides}", slides_block).replace("{transcript}", transcript_blob)
    out = call_llm(url, api_key, model, prompt)
    arr = extract_json_array(out)
    notes = _coerce_notes(arr) if arr is not None else {}
    if not notes:
        # dump raw for debugging, then signal failure so caller can fall back
        try:
            open("_llm_raw_debug.txt", "w", encoding="utf-8").write(out)
        except Exception:
            pass
        raise ValueError("LLM returned no usable mapping; raw dumped to _llm_raw_debug.txt")
    return notes


def map_by_order(meta, transcript_blob):
    """Fallback: split the transcript into N contiguous blocks by slide count."""
    slides_sorted = sorted(meta, key=lambda x: x.get("t", 0))
    n = len(slides_sorted)
    # split on blank lines first; if too few, split by equal char count
    parts = [p.strip() for p in re.split(r"\n\s*\n", transcript_blob) if p.strip()]
    if len(parts) < n:
        chars = list(transcript_blob)
        size = max(1, len(chars) // n)
        parts = []
        for i in range(n):
            chunk = "".join(chars[i * size:(i + 1) * size]).strip()
            if chunk:
                parts.append(chunk)
    notes = {}
    for i, s in enumerate(slides_sorted):
        notes[s["n"]] = parts[i] if i < len(parts) else ""
    return notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta", default="slides_meta.json")
    ap.add_argument("--transcript", required=True)
    ap.add_argument("--ocr", default="output/slides_ocr.txt")
    ap.add_argument("--outdir", default="output")
    ap.add_argument("--mode", default="auto", choices=["auto", "timestamped", "content"])
    ap.add_argument("--url", default="")
    ap.add_argument("--api-key", default="")
    ap.add_argument("--model", default="qwen3.7-max")
    ap.add_argument("--sections", default=None,
                    help="output/sections.json from build_sections.py — needs a "
                         "TIMESTAMPED transcript; adds the 【新增节】 markers to the "
                         "HTML / transcript and applies its speaker-name corrections")
    args = ap.parse_args()

    meta = load_meta(args.meta)
    ocr_by_slide = parse_ocr(args.ocr)
    # Sections are optional here: they need a TIMESTAMPED transcript (the user's
    # own export may be plain text, in which case build_sections.py cannot run).
    secs = load_sections(args.sections)
    fixes = load_name_fixes(args.sections)

    detected, payload = detect_and_parse_transcript(args.transcript)
    print(f"Transcript format detected: {detected}")

    if args.mode == "timestamped" or (args.mode == "auto" and detected == "timestamped"):
        if detected != "timestamped":
            print("[WARN] --mode timestamped but no timestamps found; falling back to content/order.")
            detected = "plain"
        else:
            notes_by_slide, assigned, total = align_by_time(meta, payload)
            print(f"Timestamped alignment: {assigned}/{total} slides got text.")
            for s in meta:
                s["notes"] = notes_by_slide.get(s["n"], "")
            if fixes:
                print("讲者姓名校正 %s -> 应用 %d 处" % (fixes, apply_name_fixes(meta, fixes)))
            _finish(meta, ocr_by_slide, args.outdir, args.meta, secs, fixes)
            return

    # plain / content mode
    blob = payload if isinstance(payload, str) else "\n".join(p["text"] for p in payload)
    notes = None
    if args.url and args.api_key:
        try:
            notes = map_by_llm(meta, blob, ocr_by_slide, args.url, args.api_key, args.model)
            print(f"LLM content-mapping done: {sum(1 for v in notes.values() if v)} slides got text.")
        except Exception as e:
            print(f"[WARN] LLM mapping failed ({e}); falling back to order-based split.", file=sys.stderr)
    if not notes:
        notes = map_by_order(meta, blob)
        print(f"Order-based fallback: {sum(1 for v in notes.values() if v)} slides got text.")
    for s in meta:
        s["notes"] = notes.get(s["n"], "")
    if fixes:
        print("讲者姓名校正 %s -> 应用 %d 处" % (fixes, apply_name_fixes(meta, fixes)))
    _finish(meta, ocr_by_slide, args.outdir, args.meta, secs, fixes)


def _finish(meta, ocr_by_slide, outdir, meta_path, sections=None, name_fixes=None):
    os.makedirs(outdir, exist_ok=True)
    save_meta(meta_path, meta)
    md = build_markdown(meta, ocr_by_slide,
                        os.path.join(outdir, "transcript_from_slides.md"),
                        sections=sections)
    tr = build_transcript_docx(meta, os.path.join(outdir, "transcript_by_speaker.docx"),
                               sections=sections, title="逐字稿 按讲者分节")
    cp = build_clean_pptx(meta, os.path.join(outdir, "slides.pptx"), sections=sections)
    vw = build_html(meta, os.path.join(outdir, "slides_viewer.html"),
                    title="幻灯片与讲稿", sections=sections, name_fixes=name_fixes)
    print(f"逐字稿     -> {tr}")
    print(f"自查对照   -> {md}")
    print(f"Slides PPTX-> {cp}")
    print(f"Viewer HTML-> {vw}")


if __name__ == "__main__":
    main()
