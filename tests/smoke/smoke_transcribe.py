"""Manual smoke test. Run as: python tests/smoke/smoke_transcribe.py

This script is NOT run by pytest. It exercises the real mlx-whisper path
end-to-end against a small fixture WAV file and will download the configured
Whisper model on first run (~1.5 GB for medium).
"""
from __future__ import annotations

import logging
import sys
import time
import wave
from pathlib import Path

import numpy as np

from whisperlite.transcribe import transcribe, warmup

MODEL = "mlx-community/whisper-medium-mlx"
LANGUAGE = "en"

FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent / "fixtures" / "hello_world.wav"
)

FIXTURE_HELP = """\
Missing fixture WAV: {path}

Generate it on macOS with:

    mkdir -p tests/fixtures
    say -o /tmp/hello_world.aiff "hello world from whisperlite"
    afconvert -f WAVE -d LEI16@16000 -c 1 /tmp/hello_world.aiff {path}

The resulting file must be 16 kHz, mono, signed 16-bit PCM.
"""


def _load_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wf:
        if wf.getframerate() != 16000:
            print(
                f"ERROR: expected 16000 Hz, got {wf.getframerate()} Hz",
                file=sys.stderr,
            )
            sys.exit(1)
        if wf.getnchannels() != 1:
            print(
                f"ERROR: expected mono, got {wf.getnchannels()} channels",
                file=sys.stderr,
            )
            sys.exit(1)
        if wf.getsampwidth() != 2:
            print(
                f"ERROR: expected 16-bit PCM, got {wf.getsampwidth() * 8}-bit",
                file=sys.stderr,
            )
            sys.exit(1)
        frames = wf.readframes(wf.getnframes())
    return np.frombuffer(frames, dtype=np.int16)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    if not FIXTURE_PATH.exists():
        print(FIXTURE_HELP.format(path=FIXTURE_PATH), file=sys.stderr)
        return 1

    audio = _load_wav(FIXTURE_PATH)
    print(f"loaded {audio.shape[0]} samples ({audio.shape[0] / 16000:.2f}s)")

    t0 = time.monotonic()
    warmup(MODEL, LANGUAGE)
    warmup_ms = (time.monotonic() - t0) * 1000.0
    print(f"warmup: {warmup_ms:.0f}ms")

    t0 = time.monotonic()
    text = transcribe(audio, MODEL, LANGUAGE)
    infer_ms = (time.monotonic() - t0) * 1000.0
    print(f"transcribe: {infer_ms:.0f}ms")
    print(f"text: {text!r}")

    if "hello" not in text.lower():
        print("FAIL: transcribed text does not contain 'hello'", file=sys.stderr)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
