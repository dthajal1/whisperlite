"""Manual smoke test. Run as: python tests/smoke/smoke_audio.py

This script is NOT run by pytest. It opens a real sounddevice InputStream
for 3 seconds against your default microphone and prints stats on the
captured audio. On first run it will trigger the macOS Microphone TCC
prompt; grant access and re-run.
"""
from __future__ import annotations

import logging
import sys
import time

import numpy as np

from whisperlite.audio import AudioRecorder
from whisperlite.errors import AudioDeviceError, AudioStreamError


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s %(message)s"
    )

    print("Recording 3 seconds of audio from your default mic. Speak now.")
    time.sleep(0.5)
    print("GO")

    recorder = AudioRecorder(sample_rate=16000, channels=1, max_seconds=10)
    try:
        recorder.start()
    except AudioDeviceError as exc:
        print(f"ERROR: could not open mic: {exc}", file=sys.stderr)
        print(
            "Check System Settings > Privacy & Security > Microphone, "
            "and confirm a default input device is configured.",
            file=sys.stderr,
        )
        return 1

    try:
        time.sleep(3.0)
        audio = recorder.stop_and_drain()
    except AudioStreamError as exc:
        print(f"ERROR: stream failed: {exc}", file=sys.stderr)
        return 1

    peak = int(np.abs(audio).max()) if audio.size else 0
    print(f"shape={audio.shape} dtype={audio.dtype} peak={peak}")

    if peak <= 100:
        print(
            f"FAIL: peak amplitude {peak} <= 100 (mic appears silent)",
            file=sys.stderr,
        )
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
