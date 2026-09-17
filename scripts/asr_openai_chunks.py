"""Transcribe named local audio chunks with the OpenAI transcription API."""
from __future__ import annotations

import argparse
import json
import mimetypes
from pathlib import Path
import re
import time
from urllib import error, request
import uuid

from asr_setup import load_api_key


CHUNK_NAME = re.compile(r"chunk_(\d+)_(\d+)\.[^.]+$")


def fmt_time(seconds: int) -> str:
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d},000"


def multipart(fields: dict[str, str], file_path: Path) -> tuple[bytes, str]:
    boundary = "----meeting-slide-" + uuid.uuid4().hex
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
            value.encode("utf-8"),
            b"\r\n",
        ])
    mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    chunks.extend([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'.encode(),
        f"Content-Type: {mime}\r\n\r\n".encode(),
        file_path.read_bytes(),
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    return b"".join(chunks), boundary


def transcribe(base_url: str, api_key: str, model: str, path: Path, prompt: str):
    fields = {"model": model, "response_format": "json"}
    if prompt:
        fields["prompt"] = prompt
    body, boundary = multipart(fields, path)
    req = request.Request(
        base_url.rstrip("/") + "/audio/transcriptions",
        data=body,
        method="POST",
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    started = time.perf_counter()
    try:
        with request.urlopen(req, timeout=900) as response:
            result = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    return str(result.get("text", "")).strip(), time.perf_counter() - started, result.get("usage")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunks-dir", required=True)
    parser.add_argument("--out-txt", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--base-url", default="https://api.openai.com/v1")
    parser.add_argument("--model", default="gpt-4o-mini-transcribe")
    parser.add_argument("--prompt", default="")
    args = parser.parse_args()

    api_key = load_api_key("openai")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is not configured; run asr_setup.py wizard")

    chunks = []
    for path in sorted(Path(args.chunks_dir).glob("chunk_*.*")):
        match = CHUNK_NAME.match(path.name)
        if match:
            chunks.append((int(match.group(1)), int(match.group(2)), path))
    if not chunks:
        raise SystemExit("no chunk_START_END audio files found")

    records, merged = [], []
    total_started = time.perf_counter()
    for index, (start, end, path) in enumerate(chunks, 1):
        text, elapsed, usage = transcribe(args.base_url, api_key, args.model, path, args.prompt)
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
        "provider": "openai",
        "model": args.model,
        "base_url": args.base_url,
        "total_elapsed_sec": round(total_elapsed, 3),
        "chunks": records,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"DONE: {total_elapsed:.2f}s -> {args.out_txt}")


if __name__ == "__main__":
    main()
