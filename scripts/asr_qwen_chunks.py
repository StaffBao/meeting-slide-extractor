"""Transcribe pre-split local audio with Qwen-Audio ASR Flash.

The API key is read only from DASHSCOPE_API_KEY. Audio chunk filenames must
contain start/end seconds as ``chunk_0000_0300.mp3``. This keeps the merged
output compatible with align_by_time.py without uploading the source to public
storage.
"""
import argparse
import base64
import json
import mimetypes
import os
from pathlib import Path
import re
import time
from urllib import error, request
from urllib.parse import urlsplit

from asr_setup import load_api_key


CHUNK_NAME = re.compile(r"chunk_(\d+)_(\d+)\.[^.]+$")


def fmt_time(seconds):
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d},000"


def transcribe(api_url, api_key, model, path, context):
    mime = mimetypes.guess_type(path.name)[0] or "audio/mpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    audio_message = {
        "role": "user",
        "content": [{
            "type": "input_audio",
            "input_audio": {
                "data": f"data:{mime};base64,{encoded}",
            },
        }],
    }
    is_audio3 = model.startswith("qwen-audio-3.0-asr-flash")
    if is_audio3:
        # Qwen-Audio 3.0 Flash uses the DashScope multimodal-generation API,
        # not OpenAI-compatible chat/completions. Filetrans is intentionally
        # excluded: it is asynchronous and requires a public file URL.
        if model.endswith("-filetrans"):
            raise ValueError(
                "Filetrans requires its asynchronous public-URL workflow; "
                "it cannot transcribe local Base64 chunks with this script")
        parts = urlsplit(api_url)
        endpoint = (
            f"{parts.scheme}://{parts.netloc}"
            "/api/v1/services/aigc/multimodal-generation/generation"
        )
        audio_format = path.suffix.lower().lstrip(".") or "mp3"
        payload_obj = {
            "model": model,
            "input": {"messages": [audio_message]},
            "parameters": {
                "format": audio_format,
                "language_hints": ["zh"],
            },
        }
        headers = {
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            "X-DashScope-SSE": "disable",
        }
    else:
        endpoint = api_url.rstrip("/") + "/chat/completions"
        messages = []
        if context:
            messages.append({"role": "system", "content": context})
        messages.append(audio_message)
        payload_obj = {
            "model": model,
            "messages": messages,
            "stream": False,
            "asr_options": {"language": "zh", "enable_itn": True},
        }
        headers = {
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
        }
    payload = json.dumps(payload_obj, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        endpoint,
        data=payload,
        method="POST",
        headers=headers,
    )
    started = time.perf_counter()
    try:
        with request.urlopen(req, timeout=600) as response:
            body = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    elapsed = time.perf_counter() - started
    if is_audio3:
        content = body["output"]["text"]
    else:
        content = body["choices"][0]["message"]["content"]
    if isinstance(content, list):
        content = "".join(str(item.get("text", "")) for item in content
                          if isinstance(item, dict))
    return str(content).strip(), elapsed, body.get("usage")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunks-dir", required=True)
    parser.add_argument("--out-txt", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", default="qwen-audio-3.0-asr-flash")
    parser.add_argument("--context", default="")
    args = parser.parse_args()

    api_key = load_api_key("qwen")
    if not api_key:
        raise SystemExit("DASHSCOPE_API_KEY is not configured; run asr_setup.py wizard")

    chunks = []
    for path in sorted(Path(args.chunks_dir).glob("chunk_*.*")):
        match = CHUNK_NAME.match(path.name)
        if match:
            chunks.append((int(match.group(1)), int(match.group(2)), path))
    if not chunks:
        raise SystemExit("no chunk_START_END audio files found")

    records = []
    merged = []
    total_started = time.perf_counter()
    for index, (start, end, path) in enumerate(chunks, 1):
        text, elapsed, usage = transcribe(
            args.base_url, api_key, args.model, path, args.context)
        records.append({
            "file": path.name,
            "start_sec": start,
            "end_sec": end,
            "elapsed_sec": round(elapsed, 3),
            "text": text,
            "usage": usage,
        })
        merged.append(f"[{fmt_time(start)}] {text}")
        print(f"[{index}/{len(chunks)}] {path.name}: {elapsed:.2f}s, {len(text)} chars")

    total_elapsed = time.perf_counter() - total_started
    Path(args.out_txt).write_text("\n".join(merged) + "\n", encoding="utf-8")
    Path(args.out_json).write_text(json.dumps({
        "model": args.model,
        "base_url": args.base_url,
        "total_elapsed_sec": round(total_elapsed, 3),
        "chunks": records,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"DONE: {total_elapsed:.2f}s -> {args.out_txt}")


if __name__ == "__main__":
    main()
