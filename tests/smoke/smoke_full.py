"""Manual end-to-end smoke test. Run as: python tests/smoke/smoke_full.py

This script is NOT run by pytest. It exercises the full whisperlite loop
against real macOS APIs: mic capture, mlx-whisper transcription, and text
injection into Notes. First run will download the configured Whisper
model (~1.5 GB for medium) and trigger the Microphone, Input Monitoring,
and Accessibility TCC prompts. Grant them and re-run.

Before running, open Notes and click inside a note's body so the cursor
is placed there — Notes will remember this on the next activation and the
injected text will land in the right spot.
"""
from __future__ import annotations

import logging
import subprocess
import sys
import time

from whisperlite.audio import AudioRecorder
from whisperlite.config import load_config
from whisperlite.errors import WhisperliteError
from whisperlite.inject import capture_focused_app, inject_text
from whisperlite.transcribe import (
    download_model,
    is_model_cached,
    transcribe,
    warmup,
)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s %(message)s"
    )

    print("Loading whisperlite end-to-end smoke test...")

    try:
        config = load_config()
    except WhisperliteError as exc:
        print(f"ERROR: failed to load config: {exc}", file=sys.stderr)
        return 1

    model_name = config.model.name
    language = config.model.language

    try:
        if not is_model_cached(model_name):
            print(f"Downloading model {model_name} (first run only)...")
            download_model(model_name)
        print(f"Warming up model {model_name}...")
        warmup(model_name, language)
    except WhisperliteError as exc:
        print(f"ERROR: model load failed: {exc}", file=sys.stderr)
        return 1

    recorder = AudioRecorder(
        sample_rate=config.audio.sample_rate,
        channels=config.audio.channels,
        max_seconds=config.audio.max_recording_seconds,
    )

    print("Recording 3 seconds. Speak now.")
    try:
        recorder.start()
        time.sleep(3.0)
        audio = recorder.stop_and_drain()
    except WhisperliteError as exc:
        print(f"ERROR: audio capture failed: {exc}", file=sys.stderr)
        return 1

    print(f"Captured {audio.shape[0]} samples.")

    try:
        text = transcribe(audio, model_name, language)
    except WhisperliteError as exc:
        print(f"ERROR: transcription failed: {exc}", file=sys.stderr)
        return 1

    print(f"Transcribed text: {text!r}")

    if not text:
        print("WARN: empty transcription; skipping inject.", file=sys.stderr)
        return 0

    try:
        subprocess.run(["open", "-a", "Notes"], check=False)
        time.sleep(1.5)
        target_pid = capture_focused_app()
        print(f"captured focused app pid={target_pid}")
        if target_pid is None:
            print("ERROR: could not capture focused app", file=sys.stderr)
            return 1
        inject_text(text, target_pid, paste_delay_ms=config.inject.paste_delay_ms)
    except WhisperliteError as exc:
        print(f"ERROR: inject failed: {exc}", file=sys.stderr)
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
