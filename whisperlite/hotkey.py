from __future__ import annotations

import logging
from typing import Callable

from pynput import keyboard
from pynput.keyboard import GlobalHotKeys

from whisperlite.errors import ConfigError, WhisperlitePermissionError

logger = logging.getLogger(__name__)


class HotkeyManager:
    """Owns the global hotkey listener that fires the record-toggle callback."""

    def __init__(
        self,
        record_keyspec: str,
        on_record_pressed: Callable[[], None],
    ) -> None:
        """Configure but do not start the listener."""
        self._keyspec = record_keyspec
        self._on_record_pressed = on_record_pressed
        self._listener: GlobalHotKeys | None = None

    def start(self) -> None:
        """Start the global hotkey listener."""
        try:
            self._listener = GlobalHotKeys({self._keyspec: self._on_record})
        except ValueError as exc:
            raise ConfigError(
                f"invalid hotkey keyspec {self._keyspec!r}: {exc}"
            ) from exc
        try:
            self._listener.start()
        except Exception as exc:
            raise WhisperlitePermissionError(
                f"failed to start hotkey listener (check Input Monitoring "
                f"and Accessibility permissions): {exc}"
            ) from exc
        logger.info("hotkey manager started with keyspec=%s", self._keyspec)

    def stop(self) -> None:
        """Stop the listener and release the OS event tap."""
        if self._listener is not None:
            try:
                self._listener.stop()
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

    def _on_record(self) -> None:
        try:
            self._on_record_pressed()
        except Exception as exc:
            logger.error("record hotkey callback raised: %s", exc)


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
