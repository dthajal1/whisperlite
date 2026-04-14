from __future__ import annotations

import logging
import subprocess
import time

from AppKit import (
    NSApplicationActivateIgnoringOtherApps,
    NSPasteboard,
    NSPasteboardItem,
    NSPasteboardTypeString,
    NSRunningApplication,
    NSWorkspace,
)
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventPost,
    CGEventSetFlags,
    kCGEventFlagMaskCommand,
    kCGHIDEventTap,
)

from whisperlite.errors import InjectError

logger = logging.getLogger(__name__)

KEYCODE_V = 9
_MODIFIER_SETTLE_SECONDS = 0.015
_ACTIVATION_POLL_INTERVAL_SECONDS = 0.05
_ACTIVATION_TIMEOUT_SECONDS = 0.5
_APPLESCRIPT_SETTLE_SECONDS = 0.15


def _force_activate(app: NSRunningApplication) -> bool:
    """Bring `app` to front, verifying focus actually transferred.

    Tries the native `activateWithOptions_` path first and polls the
    frontmost application PID until it matches. On macOS Sequoia the
    native path can be silently blocked by focus-stealing protection,
    so if that times out we fall back to an AppleScript
    `tell application "X" to activate` AppleEvent which uses a
    different (more forceful) code path.

    Returns True if the target app became frontmost, False otherwise.
    """
    target_pid = int(app.processIdentifier())

    app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)

    deadline = time.monotonic() + _ACTIVATION_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        front = NSWorkspace.sharedWorkspace().frontmostApplication()
        if front is not None and int(front.processIdentifier()) == target_pid:
            return True
        time.sleep(_ACTIVATION_POLL_INTERVAL_SECONDS)

    app_name = app.localizedName()
    if not app_name:
        logger.warning(
            "force_activate: native activation did not take effect and app has no "
            "localizedName; cannot fall back to AppleScript (target_pid=%s)",
            target_pid,
        )
        return False

    if '"' in app_name:
        logger.warning(
            "force_activate: refusing AppleScript fallback — app name %r contains "
            "a double-quote character (target_pid=%s)",
            app_name,
            target_pid,
        )
        return False

    try:
        subprocess.run(
            ["osascript", "-e", f'tell application "{app_name}" to activate'],
            capture_output=True,
            timeout=2.0,
            check=False,
        )
    except Exception as exc:
        logger.warning(
            "force_activate: AppleScript fallback raised %s (target_pid=%s)",
            exc,
            target_pid,
        )
        return False

    time.sleep(_APPLESCRIPT_SETTLE_SECONDS)

    front = NSWorkspace.sharedWorkspace().frontmostApplication()
    front_pid = int(front.processIdentifier()) if front is not None else None
    if front_pid == target_pid:
        return True

    logger.warning(
        "force_activate: could not bring target app to front "
        "(target_pid=%s, frontmost_pid=%s)",
        target_pid,
        front_pid,
    )
    return False


def capture_focused_app() -> int | None:
    """Return the PID of the currently frontmost application, or None if none."""
    try:
        workspace = NSWorkspace.sharedWorkspace()
        app = workspace.frontmostApplication()
        if app is None:
            return None
        return int(app.processIdentifier())
    except Exception as exc:
        logger.warning("capture_focused_app failed: %s", exc)
        return None


def _snapshot_pasteboard_items(
    pb: NSPasteboard,
) -> list[list[tuple[str, object]]]:
    """Deep-copy all items on the pasteboard as (type, NSData) tuples per item."""
    snapshot: list[list[tuple[str, object]]] = []
    items = pb.pasteboardItems() or []
    for item in items:
        entries: list[tuple[str, object]] = []
        for type_name in item.types() or []:
            data = item.dataForType_(type_name)
            if data is None:
                continue
            entries.append((type_name, data))
        snapshot.append(entries)
    return snapshot


def _restore_pasteboard_items(
    pb: NSPasteboard, snapshot: list[list[tuple[str, object]]]
) -> None:
    """Re-write a previously captured pasteboard snapshot back onto the pasteboard."""
    pb.clearContents()
    rebuilt = []
    for entries in snapshot:
        if not entries:
            continue
        new_item = NSPasteboardItem.alloc().init()
        for type_name, data in entries:
            new_item.setData_forType_(data, type_name)
        rebuilt.append(new_item)
    if rebuilt:
        pb.writeObjects_(rebuilt)


def _send_cmd_v() -> None:
    """Synthesize a Cmd+V keyboard event via CGEvent."""
    key_down = CGEventCreateKeyboardEvent(None, KEYCODE_V, True)
    CGEventSetFlags(key_down, kCGEventFlagMaskCommand)
    CGEventPost(kCGHIDEventTap, key_down)
    time.sleep(_MODIFIER_SETTLE_SECONDS)
    key_up = CGEventCreateKeyboardEvent(None, KEYCODE_V, False)
    CGEventSetFlags(key_up, kCGEventFlagMaskCommand)
    CGEventPost(kCGHIDEventTap, key_up)


def inject_text(
    text: str,
    target_pid: int | None,
    paste_delay_ms: int = 150,
) -> None:
    """Inject `text` at the current cursor position of the app with PID `target_pid`."""
    try:
        pb = NSPasteboard.generalPasteboard()
        saved_change_count = int(pb.changeCount())
        saved_items = _snapshot_pasteboard_items(pb)

        if target_pid is not None:
            app = NSRunningApplication.runningApplicationWithProcessIdentifier_(
                target_pid
            )
            if app is None:
                pb.clearContents()
                pb.setString_forType_(text, NSPasteboardTypeString)
                raise InjectError(
                    "target app no longer exists; text copied to clipboard instead"
                )
            if not _force_activate(app):
                pb.clearContents()
                pb.setString_forType_(text, NSPasteboardTypeString)
                raise InjectError(
                    f"could not bring target app to front (pid={target_pid}); "
                    f"text copied to clipboard — press Cmd+V manually to paste"
                )

        pb.clearContents()
        pb.setString_forType_(text, NSPasteboardTypeString)

        _send_cmd_v()

        time.sleep(paste_delay_ms / 1000.0)

        new_change_count = int(pb.changeCount())
        if (new_change_count - saved_change_count) > 2:
            logger.info(
                "pasteboard changed mid-injection, skipping restore to avoid clobbering user data"
            )
            return

        _restore_pasteboard_items(pb, saved_items)
    except InjectError:
        raise
    except Exception as exc:
        raise InjectError(f"inject failed: {exc}") from exc
