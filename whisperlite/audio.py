from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any

import numpy as np
import sounddevice as sd

from whisperlite.errors import AudioDeviceError, AudioStreamError

logger = logging.getLogger(__name__)

_BLOCKSIZE = 1024
_WATCHDOG_INTERVAL = 0.5
_WATCHDOG_TIMEOUT = 2.0
# stream.stop()/close() occasionally wedges inside PortAudio/CoreAudio on
# macOS — a C call that never returns. Run it in a daemon thread and give
# up after this many seconds so the worker can still transcribe + paste.
_STREAM_CLOSE_TIMEOUT = 2.0


def list_input_devices() -> list[dict]:
    """Return all available input devices via sounddevice.query_devices."""
    try:
        devices = sd.query_devices()
    except Exception as exc:
        raise AudioDeviceError(f"failed to query audio devices: {exc}") from exc
    return [d for d in devices if int(d.get("max_input_channels", 0)) > 0]


def get_default_input() -> dict | None:
    """Return the default input device dict, or None if no input is configured."""
    try:
        device = sd.query_devices(kind="input")
    except Exception as exc:
        logger.debug("no default input device: %s", exc)
        return None
    if not device:
        return None
    if int(device.get("max_input_channels", 0)) <= 0:
        return None
    return device


class AudioRecorder:
    """Sounddevice-backed mic recorder with a bounded capture deque."""

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        max_seconds: int = 60,
    ) -> None:
        """Configure but do not open the stream."""
        self._sample_rate = sample_rate
        self._channels = channels
        self._max_seconds = max_seconds
        self._max_frames = sample_rate * max_seconds

        self._buffer: deque[np.ndarray] = deque()
        self._stream: sd.InputStream | None = None
        self._frames_captured = 0
        self._max_duration_reached = False
        self._stream_error: str | None = None
        self._last_callback_time = 0.0
        self._watchdog: threading.Thread | None = None
        self._watchdog_stop = threading.Event()

    @property
    def is_recording(self) -> bool:
        """True if a stream is currently open and capturing."""
        return self._stream is not None and self._stream.active

    @property
    def max_duration_reached(self) -> bool:
        """True if the recording was auto-stopped by hitting the max-seconds cap."""
        return self._max_duration_reached

    def start(self) -> None:
        """Open the input stream and begin capturing into the internal deque."""
        if self.is_recording:
            logger.warning("start() called while already recording; ignoring")
            return

        if get_default_input() is None:
            raise AudioDeviceError("no input device available")

        self._buffer.clear()
        self._frames_captured = 0
        self._max_duration_reached = False
        self._stream_error = None
        self._last_callback_time = time.monotonic()

        try:
            self._stream = sd.InputStream(
                samplerate=self._sample_rate,
                channels=self._channels,
                dtype="int16",
                blocksize=_BLOCKSIZE,
                callback=self._callback,
            )
            self._stream.start()
        except Exception as exc:
            self._stream = None
            raise AudioDeviceError(f"failed to open input stream: {exc}") from exc

        self._watchdog_stop.clear()
        self._watchdog = threading.Thread(
            target=self._watchdog_loop, name="whisperlite-audio-watchdog", daemon=True
        )
        self._watchdog.start()
        logger.debug(
            "audio recording started: %d Hz %d ch cap=%ds",
            self._sample_rate,
            self._channels,
            self._max_seconds,
        )

    def stop_and_drain(self) -> np.ndarray:
        """Stop the stream and return all captured frames as a 1-D int16 numpy array."""
        self._shutdown_stream()

        if self._stream_error is not None:
            err = self._stream_error
            self._stream_error = None
            self._buffer.clear()
            raise AudioStreamError(err)

        if not self._buffer:
            return np.zeros(0, dtype=np.int16)

        chunks = list(self._buffer)
        self._buffer.clear()
        return np.concatenate(chunks).flatten().astype(np.int16, copy=False)

    def cancel(self) -> None:
        """Stop the stream and discard the buffer (no array returned)."""
        self._shutdown_stream()
        self._buffer.clear()
        self._stream_error = None

    def _callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: Any,
        status: sd.CallbackFlags,
    ) -> None:
        self._last_callback_time = time.monotonic()

        if status:
            if getattr(status, "input_overflow", False):
                logger.warning("audio input overflow: %s", status)
            else:
                logger.debug("audio callback status: %s", status)

        self._buffer.append(indata.copy())
        self._frames_captured += frames

        if self._frames_captured >= self._max_frames:
            self._max_duration_reached = True
            logger.info(
                "max recording duration reached (%ds); stopping", self._max_seconds
            )
            raise sd.CallbackStop

    def _watchdog_loop(self) -> None:
        while not self._watchdog_stop.wait(_WATCHDOG_INTERVAL):
            if self._stream is None or not self._stream.active:
                return
            if time.monotonic() - self._last_callback_time > _WATCHDOG_TIMEOUT:
                self._stream_error = "no audio callbacks for >2s, possible device stall"
                logger.error("audio watchdog: %s", self._stream_error)
                try:
                    if self._stream is not None:
                        self._stream.stop()
                except Exception as exc:
                    logger.warning(
                        "watchdog failed to stop stream cleanly: %s", exc
                    )
                return

    def _shutdown_stream(self) -> None:
        logger.info(
            "shutdown_stream: entry (stream=%s, active=%s, max_duration_reached=%s)",
            "present" if self._stream is not None else "None",
            self._stream.active if self._stream is not None else "n/a",
            self._max_duration_reached,
        )
        t0 = time.monotonic()
        self._watchdog_stop.set()
        if self._watchdog is not None:
            self._watchdog.join(timeout=1.0)
            self._watchdog = None
        logger.info(
            "shutdown_stream: watchdog joined in %.0fms",
            (time.monotonic() - t0) * 1000,
        )

        if self._stream is None:
            logger.info("shutdown_stream: stream already None, returning")
            return

        stream = self._stream
        self._stream = None

        close_done = threading.Event()
        close_error: list[BaseException | None] = [None]

        def _do_close() -> None:
            # Use abort() (Pa_AbortStream) rather than stop() (Pa_StopStream).
            # stop() waits for the audio driver's buffer queue to drain before
            # tearing down the stream, and that drain has been observed to hang
            # indefinitely inside CoreAudio on macOS. Our own _callback has
            # already appended every frame to self._buffer, so we don't need
            # drain semantics — abort()'s hard teardown is fine and more
            # reliable. The timeout below still wraps this as a safety net.
            try:
                t1 = time.monotonic()
                stream.abort()
                logger.info(
                    "shutdown_stream: stream.abort() returned in %.0fms",
                    (time.monotonic() - t1) * 1000,
                )
                t2 = time.monotonic()
                stream.close()
                logger.info(
                    "shutdown_stream: stream.close() returned in %.0fms",
                    (time.monotonic() - t2) * 1000,
                )
            except BaseException as exc:
                close_error[0] = exc
            finally:
                close_done.set()

        close_thread = threading.Thread(
            target=_do_close, name="whisperlite-audio-close", daemon=True
        )
        close_thread.start()

        if close_done.wait(_STREAM_CLOSE_TIMEOUT):
            if close_error[0] is not None:
                logger.warning(
                    "error while closing audio stream: %s", close_error[0]
                )
                if self._stream_error is None:
                    self._stream_error = f"stream close failed: {close_error[0]}"
        else:
            # PortAudio/CoreAudio hung inside stop()/close() on macOS. The
            # audio we've already buffered is safe — transcribe + paste can
            # still proceed. The mic indicator may stay lit at the OS level
            # until whisperlite is restarted.
            logger.error(
                "shutdown_stream: stream.stop()/close() did not return within %.1fs; "
                "abandoning close thread (mic indicator may stay on until restart)",
                _STREAM_CLOSE_TIMEOUT,
            )
        logger.info("shutdown_stream: done")
