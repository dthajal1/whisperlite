"""Manual smoke test. Run as: python tests/smoke/smoke_inject.py"""
from __future__ import annotations

import subprocess
import sys
import time

from whisperlite.errors import InjectError
from whisperlite.inject import capture_focused_app, inject_text

TARGET_APP = "Notes"
PAYLOAD = "hello from whisperlite smoke test"


def main() -> int:
    print(f"1. Opening {TARGET_APP}.")
    subprocess.run(["open", "-a", TARGET_APP], check=True)
    time.sleep(1.5)
    print(f"2. In {TARGET_APP}, click inside a note's body so the cursor is blinking there.")
    print("3. Come back to this terminal and press Enter.")
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        print("aborted", file=sys.stderr)
        return 1

    print(f"4. Re-activating {TARGET_APP}...")
    subprocess.run(["open", "-a", TARGET_APP], check=True)
    time.sleep(1.5)

    target_pid = capture_focused_app()
    print(f"   captured focused app pid={target_pid}")
    if target_pid is None:
        print("error: could not capture focused app", file=sys.stderr)
        return 1

    try:
        inject_text(PAYLOAD, target_pid=target_pid)
    except InjectError as exc:
        print(f"InjectError: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Done. Verify the text '{PAYLOAD}' appeared in {TARGET_APP}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
