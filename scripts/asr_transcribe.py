import argparse, os, sys, datetime, subprocess, tempfile, shutil

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

def fmt_time(sec):
    # SRT style HH:MM:SS,mmm
    if sec is None:
        return "00:00:00,000"
    h = int(sec // 3600); m = int((sec % 3600) // 60); s = int(sec % 60)
    ms = int((sec - int(sec)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--model", default="medium")
    ap.add_argument("--model-dir", default=None, help="local model directory (skip HF download)")
    ap.add_argument("--out-srt", required=True)
    ap.add_argument("--out-txt", required=True)
    ap.add_argument("--duration", type=float, default=None, help="limit seconds for test; None = full")
    ap.add_argument("--threads", type=int, default=min(8, os.cpu_count() or 4))
    ap.add_argument("--compute-type", default="int8")
    ap.add_argument("--ffmpeg", default=None,
                    help="optional; auto-detected (imageio_ffmpeg -> PATH -> MEETING_FFMPEG env)")
    args = ap.parse_args()

    from faster_whisper import WhisperModel
    model_ref = args.model_dir if args.model_dir else args.model
    print(f"[{datetime.datetime.now()}] loading model {model_ref} ({args.compute_type}) ...", flush=True)
    model = WhisperModel(model_ref, device="cpu", compute_type=args.compute_type,
                         cpu_threads=args.threads)
    print(f"[{datetime.datetime.now()}] model loaded. transcribing (duration={args.duration}) ...", flush=True)

    # faster-whisper transcribe() has no 'duration' arg; clip first via ffmpeg if requested
    audio_path = args.video
    tmp_clip = None
    if args.duration:
        ffmpeg = find_ffmpeg(args.ffmpeg)
        fd, tmp_clip = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        cmd = [ffmpeg, "-y", "-i", args.video, "-t", str(args.duration),
               "-vn", "-ac", "1", "-ar", "16000", tmp_clip]
        print(f"[{datetime.datetime.now()}] clipping {args.duration}s via ffmpeg ...", flush=True)
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        audio_path = tmp_clip

    segments, info = model.transcribe(
        audio_path,
        language="zh",
        task="transcribe",
        beam_size=5,
        vad_filter=True,
    )
    print(f"[{datetime.datetime.now()}] language={info.language} prob={info.language_probability:.2f} duration={info.duration:.1f}s", flush=True)

    srt_lines = []
    txt_lines = []
    n = 0
    for seg in segments:
        n += 1
        t0 = fmt_time(seg.start); t1 = fmt_time(seg.end)
        text = seg.text.strip()
        srt_lines.append(f"{n}\n{t0} --> {t1}\n{text}\n")
        txt_lines.append(f"[{t0}] {text}")
        if n % 50 == 0:
            print(f"[{datetime.datetime.now()}] {n} segs done ...", flush=True)

    with open(args.out_srt, "w", encoding="utf-8") as f:
        f.write("\n".join(srt_lines))
    with open(args.out_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(txt_lines))
    if tmp_clip and os.path.exists(tmp_clip):
        try: os.remove(tmp_clip)
        except OSError: pass
    print(f"[{datetime.datetime.now()}] DONE. {n} segments written to {args.out_srt} / {args.out_txt}", flush=True)

if __name__ == "__main__":
    main()
