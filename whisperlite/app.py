from __future__ import annotations

import logging
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Union

import psutil
import rumps

from whisperlite.audio import AudioRecorder
from whisperlite.config import (
    Config,
    ensure_config_exists,
    get_effective_config_path,
)
from whisperlite.errors import (
    ModelDownloadError,
    ModelLoadError,
    WhisperliteError,
)
from whisperlite.hotkey import CancelListener, HotkeyManager
from whisperlite.inject import inject_text
from whisperlite.sounds import play
from whisperlite.transcribe import download_model, is_model_cached, transcribe, warmup

logger = logging.getLogger(__name__)

_DOWNLOADING_TITLE = "\u2b07\ufe0f"
_DISABLED_TITLE = "\U0001f6ab"
_KVK_SHIFT = 56
_INJECT_WAIT_TIMEOUT_S = 0.5
_DOWNLOAD_JOIN_TIMEOUT_S = 1.0
_WORKER_JOIN_TIMEOUT_S = 2.0
_QUEUE_POLL_S = 0.5

# macOS deeplinks into the relevant Privacy panes. Used by the disabled-state
# "Fix in System Settings" menu action.
_SETTINGS_URL_MICROPHONE = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"
)
_SETTINGS_URL_ACCESSIBILITY = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
)

# Pretty names for the modifier strings pynput accepts, used in the welcome
# message. Falls back to the raw name.
_HOTKEY_DISPLAY_NAMES = {
    "alt": "Option",
    "alt_l": "Option",
    "alt_r": "Option",
    "ctrl": "Control",
    "ctrl_l": "Control",
    "ctrl_r": "Control",
    "cmd": "Command",
    "cmd_l": "Command",
    "cmd_r": "Command",
    "shift": "Shift",
}


class State(str, Enum):
    """Top-level state of the coordinator/menubar app."""

    INITIALIZING = "initializing"
    DOWNLOADING = "downloading"
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    INJECTING = "injecting"
    ERROR = "error"
    DISABLED = "disabled"


@dataclass(frozen=True)
class HotkeyPressed:
    """User pressed the record hotkey."""


@dataclass(frozen=True)
class CancelPressed:
    """User pressed Escape while recording."""


@dataclass(frozen=True)
class MaxDurationReached:
    """Recording hit the configured max-seconds cap."""


@dataclass(frozen=True)
class ModelReady:
    """Background model download + warmup finished successfully."""


@dataclass(frozen=True)
class ModelDownloadFailed:
    """Background model download or warmup raised."""

    error: str


@dataclass(frozen=True)
class ShutdownRequested:
    """Sentinel posted to the queue to stop the worker loop."""


Event = Union[
    HotkeyPressed,
    CancelPressed,
    MaxDurationReached,
    ModelReady,
    ModelDownloadFailed,
    ShutdownRequested,
]


class WhisperliteApp(rumps.App):
    """Menubar app, coordinator worker thread, state machine, event queue."""

    def __init__(self, config: Config) -> None:
        """Build the rumps app and the coordinator state (no threads started yet)."""
        super().__init__(
            name="whisperlite",
            title=None,
            icon=str(config.ui.idle_icon),
            template=True,
            quit_button=None,
        )
        self._config = config
        self._state: State = State.INITIALIZING
        self._queue: queue.Queue[Event] = queue.Queue()
        self._worker_thread: threading.Thread | None = None
        self._shutting_down = False
        self._last_error: str | None = None
        self._recording_started_at: float | None = None
        self._max_duration_timer: threading.Timer | None = None
        self._download_thread: threading.Thread | None = None
        self._download_cancelled = threading.Event()
        self._cancel_requested: bool = False
        self._announced_ready: bool = False
        self._disabled_settings_url: str | None = None

        self._recorder = AudioRecorder(
            sample_rate=config.audio.sample_rate,
            channels=config.audio.channels,
            max_seconds=config.audio.max_recording_seconds,
        )
        self._hotkey_manager: HotkeyManager | None = None
        self._cancel_listener: CancelListener | None = None

        self._status_item = rumps.MenuItem("Status: initializing")
        self._status_item.set_callback(None)
        self._last_error_item = rumps.MenuItem("")
        self._last_error_item.set_callback(None)
        self._fix_in_settings_item = rumps.MenuItem("")
        self._fix_in_settings_item.set_callback(None)
        self._setup_menu()

    def _setup_menu(self) -> None:
        self.menu = [
            self._status_item,
            self._last_error_item,
            self._fix_in_settings_item,
            None,
            rumps.MenuItem("Open Config File", callback=self._on_open_config),
            rumps.MenuItem("Open Log File", callback=self._on_open_log),
            None,
            rumps.MenuItem("Quit", callback=self._on_quit),
        ]
        self._last_error_item.title = ""
        self._fix_in_settings_item.title = ""

    def start_worker(self) -> None:
        """Spawn the coordinator worker thread."""
        if self._worker_thread is not None and self._worker_thread.is_alive():
            return
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="whisperlite-worker",
            daemon=True,
        )
        self._worker_thread.start()
        logger.info("worker thread started")

    def post_launch_init(self) -> None:
        """Run TCC-sensitive init after the NSApplication run loop is up."""
        logger.info("post_launch_init starting")

        try:
            self._probe_microphone()
        except Exception as exc:
            logger.error("microphone probe failed: %s", exc)
            self._enter_disabled(
                "Needs microphone access — click below to fix.",
                settings_url=_SETTINGS_URL_MICROPHONE,
            )
            return

        if is_model_cached(self._config.model.name):
            try:
                warmup(self._config.model.name, self._config.model.language)
            except ModelLoadError as exc:
                logger.error("warmup failed: %s", exc)
                self._enter_disabled(
                    "Couldn't load the whisper model. Check the log "
                    "for details."
                )
                return
        else:
            sys.stderr.write(
                "\nwhisperlite — first run, fetching the whisper model "
                "(~1.5 GB, one-time)…\n"
            )
            sys.stderr.flush()
            self._set_state(State.DOWNLOADING, title=_DOWNLOADING_TITLE)
            self._spawn_download_thread()

        try:
            self._hotkey_manager = HotkeyManager(
                modifier=self._config.hotkey.record,
                double_tap_window_ms=self._config.hotkey.double_tap_window_ms,
                on_record_pressed=self._on_hotkey_pressed,
            )
            self._hotkey_manager.start()
        except WhisperliteError as exc:
            logger.error("hotkey manager start failed: %s", exc)
            self._enter_disabled(
                "Needs accessibility access — click below to fix.",
                settings_url=_SETTINGS_URL_ACCESSIBILITY,
            )
            return

        self._trigger_accessibility_prompt()

        if self._state == State.INITIALIZING:
            self._set_state(State.IDLE, icon=self._config.ui.idle_icon)
            self._announce_ready()
        logger.info("post_launch_init done, state=%s", self._state)

    def _probe_microphone(self) -> None:
        import sounddevice as sd

        stream = sd.InputStream(
            samplerate=self._config.audio.sample_rate,
            channels=self._config.audio.channels,
            dtype="int16",
        )
        try:
            stream.start()
            time.sleep(0.1)
        finally:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    def _trigger_accessibility_prompt(self) -> None:
        try:
            from Quartz import CGEventCreateKeyboardEvent, CGEventPost, kCGHIDEventTap

            down = CGEventCreateKeyboardEvent(None, _KVK_SHIFT, True)
            up = CGEventCreateKeyboardEvent(None, _KVK_SHIFT, False)
            CGEventPost(kCGHIDEventTap, down)
            CGEventPost(kCGHIDEventTap, up)
        except Exception as exc:
            logger.warning(
                "accessibility probe failed (first paste will prompt instead): %s", exc
            )

    def _spawn_download_thread(self) -> None:
        self._download_cancelled.clear()

        def _download() -> None:
            try:
                download_model(self._config.model.name)
                if self._download_cancelled.is_set():
                    return
                warmup(self._config.model.name, self._config.model.language)
                self._queue.put(ModelReady())
            except (ModelDownloadError, ModelLoadError) as exc:
                self._queue.put(ModelDownloadFailed(error=str(exc)))
            except Exception as exc:
                self._queue.put(ModelDownloadFailed(error=f"unexpected: {exc}"))

        self._download_thread = threading.Thread(
            target=_download, name="whisperlite-download", daemon=True
        )
        self._download_thread.start()

    def shutdown(self) -> None:
        """Run the teardown protocol in the documented order."""
        if self._shutting_down:
            return
        self._shutting_down = True
        logger.info("shutdown starting")

        try:
            if self._cancel_listener is not None:
                self._cancel_listener.stop()
                self._cancel_listener = None
        except Exception as exc:
            logger.warning("shutdown: cancel listener stop failed: %s", exc)

        try:
            if self._state == State.INJECTING:
                waited = 0.0
                while self._state == State.INJECTING and waited < _INJECT_WAIT_TIMEOUT_S:
                    time.sleep(0.05)
                    waited += 0.05
        except Exception as exc:
            logger.warning("shutdown: inject wait failed: %s", exc)

        try:
            if self._recorder.is_recording:
                self._recorder.cancel()
        except Exception as exc:
            logger.warning("shutdown: recorder stop failed: %s", exc)

        try:
            if self._max_duration_timer is not None:
                self._max_duration_timer.cancel()
                self._max_duration_timer = None
        except Exception as exc:
            logger.warning("shutdown: max-duration timer cancel failed: %s", exc)

        try:
            if self._hotkey_manager is not None:
                self._hotkey_manager.stop()
                self._hotkey_manager = None
        except Exception as exc:
            logger.warning("shutdown: hotkey manager stop failed: %s", exc)

        try:
            self._download_cancelled.set()
            if self._download_thread is not None and self._download_thread.is_alive():
                self._download_thread.join(timeout=_DOWNLOAD_JOIN_TIMEOUT_S)
        except Exception as exc:
            logger.warning("shutdown: download thread join failed: %s", exc)

        try:
            self._drain_queue()
            self._queue.put(ShutdownRequested())
        except Exception as exc:
            logger.warning("shutdown: queue drain failed: %s", exc)

        try:
            if self._worker_thread is not None and self._worker_thread.is_alive():
                self._worker_thread.join(timeout=_WORKER_JOIN_TIMEOUT_S)
        except Exception as exc:
            logger.warning("shutdown: worker join failed: %s", exc)

        try:
            for handler in list(logging.getLogger().handlers):
                handler.flush()
        except Exception:
            pass

        logger.info("shutdown done")

    def _drain_queue(self) -> None:
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            return

    def _on_quit(self, _: rumps.MenuItem) -> None:
        self.shutdown()
        rumps.quit_application()

    def _on_open_config(self, _: rumps.MenuItem) -> None:
        try:
            path = get_effective_config_path()
            ensure_config_exists(path)
            logger.info("opening config file at %s", path)
            subprocess.run(["open", str(path)], check=False)
        except Exception as exc:
            logger.warning("failed to open config file: %s", exc)

    def _on_open_log(self, _: rumps.MenuItem) -> None:
        path = Path(self._config.log.path).expanduser()
        try:
            subprocess.run(["open", str(path)], check=False)
        except Exception as exc:
            logger.warning("failed to open log file %s: %s", path, exc)

    @rumps.timer(900)
    def heartbeat(self, _: rumps.Timer) -> None:
        """Log RSS and state every 15 minutes; warn if stuck in RECORDING."""
        try:
            rss_mb = psutil.Process().memory_info().rss / (1024 * 1024)
        except Exception:
            rss_mb = -1.0
        logger.info("heartbeat rss=%.1fMB state=%s", rss_mb, self._state)
        if self._state == State.RECORDING and self._recording_started_at is not None:
            elapsed = time.monotonic() - self._recording_started_at
            if elapsed > self._config.audio.max_recording_seconds + 5:
                logger.warning(
                    "stuck in RECORDING for %.1fs (>max_recording_seconds + 5)", elapsed
                )

    def _on_hotkey_pressed(self) -> None:
        self._queue.put(HotkeyPressed())

    def _on_max_duration_timer(self) -> None:
        logger.info("max-duration timer fired, enqueuing MaxDurationReached")
        self._queue.put(MaxDurationReached())

    def _on_cancel_pressed(self) -> None:
        # Set the flag synchronously so the worker thread's checkpoints in
        # _finish_recording_and_transcribe (which runs long — transcribe +
        # inject can take hundreds of ms) can observe it without waiting for
        # the queue to drain. The queued event still fires the RECORDING-state
        # sync cancel path when the worker is idle.
        self._cancel_requested = True
        self._queue.put(CancelPressed())

    def _worker_loop(self) -> None:
        while not self._shutting_down:
            try:
                event = self._queue.get(timeout=_QUEUE_POLL_S)
            except queue.Empty:
                continue
            logger.info(
                "worker dequeued %s in state %s",
                type(event).__name__,
                self._state.value,
            )
            if isinstance(event, ShutdownRequested):
                return
            try:
                self._handle_event(event)
            except WhisperliteError as exc:
                self._enter_error_state(str(exc), exc_info=False)
            except Exception as exc:
                logger.exception("unexpected error in worker")
                self._enter_error_state(f"unexpected error: {exc}", exc_info=True)

    def _handle_event(self, event: Event) -> None:
        """Dispatch one event according to the current state."""
        if self._shutting_down:
            return

        if isinstance(event, ShutdownRequested):
            return

        if isinstance(event, ModelReady):
            if self._state == State.DOWNLOADING:
                self._set_state(State.IDLE, icon=self._config.ui.idle_icon)
                self._announce_ready()
            return

        if isinstance(event, ModelDownloadFailed):
            logger.error("model download failed: %s", event.error)
            self._enter_disabled(
                "Couldn't download the whisper model. Check your "
                "internet connection and restart whisperlite."
            )
            return

        if self._state == State.ERROR:
            self._last_error = None
            self._last_error_item.title = ""
            self._set_state(State.IDLE, icon=self._config.ui.idle_icon)

        if isinstance(event, HotkeyPressed):
            if self._state == State.IDLE:
                self._start_recording()
            elif self._state == State.RECORDING:
                self._finish_recording_and_transcribe()
            else:
                logger.warning(
                    "hotkey pressed in state %s, ignoring", self._state
                )
            return

        if isinstance(event, CancelPressed):
            if self._state == State.RECORDING:
                self._cancel_recording()
            elif self._state in (State.TRANSCRIBING, State.INJECTING):
                logger.info(
                    "cancel requested during %s, will abort at next checkpoint",
                    self._state.value,
                )
                self._cancel_requested = True
            else:
                logger.debug("cancel pressed in state %s, ignoring", self._state)
            return

        if isinstance(event, MaxDurationReached):
            if self._state == State.RECORDING:
                self._finish_recording_and_transcribe()
            return

    def _start_recording(self) -> None:
        self._cancel_requested = False
        self._recorder.start()
        try:
            self._cancel_listener = CancelListener(on_cancel=self._on_cancel_pressed)
            self._cancel_listener.start()
        except Exception as exc:
            logger.warning("failed to start cancel listener: %s", exc)
            self._cancel_listener = None

        self._max_duration_timer = threading.Timer(
            self._config.audio.max_recording_seconds,
            self._on_max_duration_timer,
        )
        self._max_duration_timer.daemon = True
        self._max_duration_timer.start()
        self._recording_started_at = time.monotonic()
        self._set_state(State.RECORDING, icon=self._config.ui.recording_icon)
        if self._config.sound.enabled:
            play(self._config.sound.start_path)

    def _finish_recording_and_transcribe(self) -> None:
        self._cancel_max_duration_timer()
        self._recording_started_at = None

        # Checkpoint 1: cancel before we even drain audio.
        if self._cancel_requested:
            logger.info("cancel requested before drain; aborting")
            self._abort_to_idle()
            return

        if self._config.sound.enabled:
            play(self._config.sound.stop_path)
        audio = self._recorder.stop_and_drain()

        # Checkpoint 2: cancel after drain but before transcribe.
        if self._cancel_requested:
            logger.info("cancel requested after drain; discarding audio")
            self._abort_to_idle()
            return

        self._set_state(State.TRANSCRIBING, icon=self._config.ui.recording_icon)
        text = transcribe(
            audio, self._config.model.name, self._config.model.language
        )
        logger.info("transcribed %d chars: %r", len(text), text)

        # Checkpoint 3: cancel after transcribe but before inject.
        if self._cancel_requested:
            logger.info("cancel requested mid-transcribe; discarding result")
            self._abort_to_idle()
            return

        if not text:
            logger.info("empty transcription, returning to idle")
            self._stop_cancel_listener()
            self._set_state(State.IDLE, icon=self._config.ui.idle_icon)
            return

        self._set_state(State.INJECTING, icon=self._config.ui.recording_icon)
        inject_text(text, paste_delay_ms=self._config.inject.paste_delay_ms)

        # Checkpoint 4: inject is atomic — if a cancel snuck in during the
        # paste window, log it but the text already landed.
        if self._cancel_requested:
            logger.warning(
                "cancel requested but paste already completed; user text was injected"
            )
            self._cancel_requested = False

        self._stop_cancel_listener()
        self._set_state(State.IDLE, icon=self._config.ui.idle_icon)

    def _cancel_recording(self) -> None:
        logger.info("cancel requested during RECORDING")
        self._abort_to_idle()

    def _abort_to_idle(self) -> None:
        """Single cleanup path used by every cancel scenario.

        Safe to call from any in-progress state (RECORDING, TRANSCRIBING,
        INJECTING). Stops timers, cancels the recorder if still running,
        plays the stop sound as audible confirmation, tears down the cancel
        listener, and transitions to IDLE.
        """
        self._cancel_requested = False
        self._cancel_max_duration_timer()
        self._recording_started_at = None
        try:
            self._recorder.cancel()
        except Exception as exc:
            logger.warning("recorder cancel raised: %s", exc)
        if self._config.sound.enabled:
            try:
                play(self._config.sound.stop_path)
            except Exception as exc:
                logger.warning("cancel stop-sound play raised: %s", exc)
        self._stop_cancel_listener()
        self._set_state(State.IDLE, icon=self._config.ui.idle_icon)

    def _stop_cancel_listener(self) -> None:
        if self._cancel_listener is not None:
            try:
                self._cancel_listener.stop()
            except Exception as exc:
                logger.warning("cancel listener stop raised: %s", exc)
            self._cancel_listener = None

    def _cancel_max_duration_timer(self) -> None:
        if self._max_duration_timer is not None:
            try:
                self._max_duration_timer.cancel()
            except Exception:
                pass
            self._max_duration_timer = None

    def _set_state(
        self,
        new_state: State,
        icon: Path | None = None,
        title: str | None = None,
    ) -> None:
        self._state = new_state
        if icon is not None:
            self.title = None
            self.icon = str(icon)
        elif title is not None:
            self.icon = None
            self.title = title
        self._status_item.title = f"Status: {new_state.value}"
        logger.info("state -> %s", new_state.value)

    def _enter_error_state(self, message: str, exc_info: bool) -> None:
        self._last_error = message
        self._last_error_item.title = f"Last error: {message}"
        if exc_info:
            logger.error("entering ERROR state: %s", message)
        else:
            logger.warning("entering ERROR state: %s", message)
        self._cancel_max_duration_timer()
        self._stop_cancel_listener()
        try:
            if self._recorder.is_recording:
                self._recorder.cancel()
        except Exception:
            pass
        self._recording_started_at = None
        self._set_state(State.ERROR, icon=self._config.ui.error_icon)

    def _enter_disabled(
        self, message: str, settings_url: str | None = None
    ) -> None:
        self._last_error = message
        self._last_error_item.title = message
        if settings_url is not None:
            self._disabled_settings_url = settings_url
            self._fix_in_settings_item.title = "Fix in System Settings"
            self._fix_in_settings_item.set_callback(self._on_open_disabled_settings)
        else:
            self._disabled_settings_url = None
            self._fix_in_settings_item.title = ""
            self._fix_in_settings_item.set_callback(None)
        logger.error("entering DISABLED state: %s", message)
        self._set_state(State.DISABLED, title=_DISABLED_TITLE)

    def _on_open_disabled_settings(self, _: rumps.MenuItem) -> None:
        url = self._disabled_settings_url
        if not url:
            return
        try:
            subprocess.run(["open", url], check=False)
        except Exception as exc:
            logger.warning("failed to open system settings deeplink: %s", exc)

    def _format_hotkey(self) -> str:
        """Render the configured record hotkey as a human-friendly string."""
        raw = self._config.hotkey.record.strip("<>").lower()
        pretty = _HOTKEY_DISPLAY_NAMES.get(raw, raw.capitalize())
        return f"double-tap {pretty}"

    def _announce_ready(self) -> None:
        """Print the welcome line once the model is loaded and hotkey is live."""
        if self._announced_ready:
            return
        self._announced_ready = True
        sys.stderr.write(
            f"\nwhisperlite — ready.\n"
            f"{self._format_hotkey()} anywhere to dictate.\n"
            f"press Escape anytime to cancel.\n"
        )
        sys.stderr.flush()
