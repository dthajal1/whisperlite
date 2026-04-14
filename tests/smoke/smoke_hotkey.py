"""Manual smoke test. Run as: python tests/smoke/smoke_hotkey.py"""
from __future__ import annotations

import logging
import sys
import time

from whisperlite.config import load_config
from whisperlite.errors import WhisperlitePermissionError
from whisperlite.hotkey import HotkeyManager


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    cfg = load_config()
    record_keyspec = cfg.hotkey.record
    print(f"Press {record_keyspec} within 30 seconds. Press Ctrl+C to abort.")

    pressed = {"flag": False}

    def on_record() -> None:
        pressed["flag"] = True
        print("Got hotkey!")

    mgr = HotkeyManager(record_keyspec=record_keyspec, on_record_pressed=on_record)

    try:
        mgr.start()
    except WhisperlitePermissionError as exc:
        print(f"FAIL: could not start hotkey listener: {exc}")
        print("Grant Input Monitoring and Accessibility permissions to your "
              "terminal/python binary in System Settings > Privacy & Security.")
        return 1

    try:
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline and not pressed["flag"]:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("Aborted by user.")
        mgr.stop()
        return 1

    mgr.stop()

    if pressed["flag"]:
        print("PASS")
        return 0
    print(f"FAIL: hotkey never received within timeout. Check Input Monitoring "
          f"+ Accessibility permissions in System Settings, and verify "
          f"{record_keyspec} is not bound to another app.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
