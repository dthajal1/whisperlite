from __future__ import annotations

import logging
import time
from typing import Callable

from pynput import keyboard
from pynput.keyboard import Key

from whisperlite.errors import ConfigError, WhisperlitePermissionError

logger = logging.getLogger(__name__)

_MAX_TAP_HOLD_SECONDS = 0.3

_MODIFIER_KEYSPEC_TO_KEY: dict[str, Key] = {
    "<alt>": Key.alt,
    "<shift>": Key.shift,
    "<ctrl>": Key.ctrl,
    "<cmd>": Key.cmd,
}

_CANONICALIZATION: dict[Key, Key] = {
    Key.alt_l: Key.alt,
    Key.alt_r: Key.alt,
    Key.alt_gr: Key.alt,
    Key.shift_l: Key.shift,
    Key.shift_r: Key.shift,
    Key.ctrl_l: Key.ctrl,
    Key.ctrl_r: Key.ctrl,
    Key.cmd_l: Key.cmd,
    Key.cmd_r: Key.cmd,
}


def _canonicalize(key: object) -> Key | None:
    """Map left/right modifier variants to their canonical Key; None for non-Key."""
    if not isinstance(key, Key):
        return None
    return _CANONICALIZATION.get(key, key)


class HotkeyManager:
    """Double-tap modifier listener that fires the record-toggle callback."""

    def __init__(
        self,
        modifier: str,
        double_tap_window_ms: int,
        on_record_pressed: Callable[[], None],
    ) -> None:
        """Configure but do not start the listener."""
        self._modifier_keyspec = modifier
        self._tap_window_seconds = double_tap_window_ms / 1000.0
        self._on_record_pressed = on_record_pressed
        self._listener: keyboard.Listener | None = None
        self._watched_key: Key | None = None

        self._modifier_is_down: bool = False
        self._modifier_press_time: float | None = None
        self._chord_detected_during_press: bool = False
        self._last_complete_tap_time: float | None = None

    def start(self) -> None:
        """Start the pynput keyboard listener."""
        watched = _MODIFIER_KEYSPEC_TO_KEY.get(self._modifier_keyspec)
        if watched is None:
            raise ConfigError(
                "hotkey.record must be one of <alt>/<shift>/<ctrl>/<cmd>, "
                f"got: {self._modifier_keyspec!r}"
            )
        self._watched_key = watched
        try:
            self._listener = keyboard.Listener(
                on_press=self._on_press,
                on_release=self._on_release,
            )
            self._listener.start()
        except Exception as exc:
            raise WhisperlitePermissionError(
                f"failed to start hotkey listener (check Input Monitoring "
                f"and Accessibility permissions): {exc}"
            ) from exc
        logger.info(
            "hotkey manager started: double-tap %s within %dms",
            self._modifier_keyspec,
            int(self._tap_window_seconds * 1000),
        )

    def stop(self) -> None:
        """Stop the listener and join its thread. Idempotent."""
        if self._listener is not None:
            try:
                self._listener.stop()
                join = getattr(self._listener, "join", None)
                if callable(join):
                    try:
                        join(timeout=1.0)
                    except Exception as exc:
                        logger.warning("hotkey listener join failed: %s", exc)
            except Exception as exc:
                logger.error("error stopping hotkey listener: %s", exc)
            self._listener = None
            logger.info("hotkey manager stopped")

    @property
    def is_running(self) -> bool:
        """Return True if the underlying pynput listener is running."""
        return self._listener is not None and bool(
            getattr(self._listener, "running", False)
        )

    def _reset_press_state(self) -> None:
        self._modifier_is_down = False
        self._modifier_press_time = None
        self._chord_detected_during_press = False

    def _on_press(self, key: object) -> None:
        canonical = _canonicalize(key)
        if canonical is None:
            if self._modifier_is_down:
                self._chord_detected_during_press = True
            return
        if canonical == self._watched_key:
            if self._modifier_is_down:
                return
            self._modifier_is_down = True
            self._modifier_press_time = time.monotonic()
            self._chord_detected_during_press = False
            return
        if self._modifier_is_down:
            self._chord_detected_during_press = True

    def _on_release(self, key: object) -> None:
        canonical = _canonicalize(key)
        if canonical is None or canonical != self._watched_key:
            return
        if not self._modifier_is_down:
            return

        press_time = self._modifier_press_time
        chord_seen = self._chord_detected_during_press
        self._reset_press_state()

        if press_time is None:
            return
        hold_duration = time.monotonic() - press_time
        if chord_seen or hold_duration > _MAX_TAP_HOLD_SECONDS:
            return

        now = time.monotonic()
        if (
            self._last_complete_tap_time is not None
            and (now - self._last_complete_tap_time) <= self._tap_window_seconds
        ):
            self._last_complete_tap_time = None
            try:
                self._on_record_pressed()
            except Exception as exc:
                logger.error("record hotkey callback raised: %s", exc)
            return
        self._last_complete_tap_time = now


class CancelListener:
    """A short-lived listener that watches for Escape during a recording."""

    def __init__(self, on_cancel: Callable[[], None]) -> None:
        """Configure the cancel listener with the user's on_cancel callback."""
        self._on_cancel = on_cancel
        self._listener: keyboard.Listener | None = None

    def start(self) -> None:
        """Start the listener (a separate pynput.keyboard.Listener instance)."""
        self._listener = keyboard.Listener(on_press=self._on_press)
        self._listener.start()
        logger.info("cancel listener started")

    def stop(self) -> None:
        """Stop the listener and join its thread."""
        if self._listener is not None:
            try:
                self._listener.stop()
                self._listener.join(timeout=1.0)
            except Exception as exc:
                logger.error("error stopping cancel listener: %s", exc)
            self._listener = None
            logger.info("cancel listener stopped")

    @property
    def is_running(self) -> bool:
        """Return True if the underlying pynput listener is running."""
        return self._listener is not None and bool(
            getattr(self._listener, "running", False)
        )

    def _on_press(self, key: object) -> bool | None:
        if key == keyboard.Key.esc:
            try:
                self._on_cancel()
            except Exception as exc:
                logger.error("cancel callback raised: %s", exc)
            return False
        return None
