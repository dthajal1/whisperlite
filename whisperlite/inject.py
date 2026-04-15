from __future__ import annotations

import logging
import time

from AppKit import (
    NSPasteboard,
    NSPasteboardItem,
    NSPasteboardTypeString,
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


def inject_text(text: str, paste_delay_ms: int = 150) -> None:
    """Inject `text` at the current cursor position of the frontmost app."""
    try:
        pb = NSPasteboard.generalPasteboard()
        saved_change_count = int(pb.changeCount())
        saved_items = _snapshot_pasteboard_items(pb)

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
