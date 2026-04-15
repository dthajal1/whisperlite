"""Manual smoke test. Run as: python tests/smoke/smoke_hotkey.py"""
from __future__ import annotations

import logging
import sys
import time

from whisperlite.config import load_config
from whisperlite.errors import WhisperlitePermissionError
from whisperlite.hotkey import HotkeyManager


_MODIFIER_HUMAN_NAMES: dict[str, str] = {
    "<alt>": "Option (Opt/Alt)",
    "<shift>": "Shift",
    "<ctrl>": "Control",
    "<cmd>": "Command",
}


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    cfg = load_config()
    record_modifier = cfg.hotkey.record
    human_name = _MODIFIER_HUMAN_NAMES.get(record_modifier, record_modifier)
    window_ms = cfg.hotkey.double_tap_window_ms
    print(
        f"Double-tap {human_name} (within {window_ms}ms) within 30 seconds. "
        "Press Ctrl+C to abort."
    )

    pressed = {"flag": False}

    def on_record() -> None:
        pressed["flag"] = True
        print("Got double-tap!")

    mgr = HotkeyManager(
        modifier=record_modifier,
        double_tap_window_ms=window_ms,
        on_record_pressed=on_record,
    )

    try:
        mgr.start()
    except WhisperlitePermissionError as exc:
        print(f"FAIL: could not start hotkey listener: {exc}")
        print(
            "Grant Input Monitoring and Accessibility permissions to your "
            "terminal/python binary in System Settings > Privacy & Security."
        )
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
    print(
        f"FAIL: double-tap never received within timeout. Check Input "
        f"Monitoring + Accessibility permissions in System Settings, and "
        f"verify no key-remap utility (Karabiner, etc.) is intercepting "
        f"{human_name}."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
