from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest

from whisperlite.config import (
    AudioConfig,
    Config,
    HotkeyConfig,
    InjectConfig,
    LogConfig,
    ModelConfig,
    SoundConfig,
    UIConfig,
    _DEFAULT_ERROR_ICON,
    _DEFAULT_IDLE_ICON,
    _DEFAULT_RECORDING_ICON,
    _DEFAULT_START_SOUND,
    _DEFAULT_STOP_SOUND,
)
from whisperlite.errors import TranscribeError, WhisperlitePermissionError


@pytest.fixture
def fake_config() -> Config:
    return Config(
        model=ModelConfig(name="fake/model", language="en"),
        hotkey=HotkeyConfig(record="<alt>", double_tap_window_ms=400),
        audio=AudioConfig(max_recording_seconds=10, sample_rate=16000, channels=1),
        inject=InjectConfig(paste_delay_ms=10),
        ui=UIConfig(
            idle_icon=_DEFAULT_IDLE_ICON,
            recording_icon=_DEFAULT_RECORDING_ICON,
            error_icon=_DEFAULT_ERROR_ICON,
        ),
        log=LogConfig(level="INFO", path="/tmp/whisperlite-test.log"),
        sound=SoundConfig(
            enabled=False,
            start_path=_DEFAULT_START_SOUND,
            stop_path=_DEFAULT_STOP_SOUND,
        ),
    )


@pytest.fixture
def mocks(mocker):
    recorder_instance = MagicMock()
    recorder_instance.is_recording = False
    recorder_instance.stop_and_drain.return_value = b"fakeaudio"

    mocker.patch(
        "whisperlite.app.AudioRecorder", return_value=recorder_instance
    )

    hotkey_instance = MagicMock()
    hotkey_instance.is_running = False
    mocker.patch("whisperlite.app.HotkeyManager", return_value=hotkey_instance)

    cancel_instance = MagicMock()
    cancel_instance.is_running = False
    mocker.patch("whisperlite.app.CancelListener", return_value=cancel_instance)

    transcribe_mock = mocker.patch(
        "whisperlite.app.transcribe", return_value="hello world"
    )
    warmup_mock = mocker.patch("whisperlite.app.warmup")
    is_cached_mock = mocker.patch(
        "whisperlite.app.is_model_cached", return_value=True
    )
    download_mock = mocker.patch("whisperlite.app.download_model")
    inject_mock = mocker.patch("whisperlite.app.inject_text")
    play_mock = mocker.patch("whisperlite.app.play")

    return {
        "recorder": recorder_instance,
        "hotkey_manager": hotkey_instance,
        "cancel_listener": cancel_instance,
        "transcribe": transcribe_mock,
        "warmup": warmup_mock,
        "is_model_cached": is_cached_mock,
        "download_model": download_mock,
        "inject_text": inject_mock,
        "play": play_mock,
    }


@pytest.fixture
def app(mocks, fake_config):
    from whisperlite.app import WhisperliteApp

    instance = WhisperliteApp(fake_config)
    yield instance
    if instance._max_duration_timer is not None:
        instance._max_duration_timer.cancel()


def _make_idle(app) -> None:
    from whisperlite.app import State

    app._set_state(State.IDLE, icon=_DEFAULT_IDLE_ICON)


def test_state_machine_idle_to_recording_on_hotkey(app, mocks):
    from whisperlite.app import HotkeyPressed, State

    _make_idle(app)
    app._handle_event(HotkeyPressed())

    assert app._state == State.RECORDING
    mocks["recorder"].start.assert_called_once()


def test_state_machine_recording_to_idle_via_hotkey_again(app, mocks):
    from whisperlite.app import HotkeyPressed, State

    _make_idle(app)
    app._handle_event(HotkeyPressed())
    assert app._state == State.RECORDING

    app._handle_event(HotkeyPressed())

    assert app._state == State.IDLE
    mocks["recorder"].stop_and_drain.assert_called_once()
    mocks["transcribe"].assert_called_once()
    mocks["inject_text"].assert_called_once()
    args, kwargs = mocks["inject_text"].call_args
    assert args[0] == "hello world"


def test_state_machine_cancel_mid_recording(app, mocks):
    from whisperlite.app import CancelPressed, HotkeyPressed, State

    _make_idle(app)
    app._handle_event(HotkeyPressed())
    assert app._state == State.RECORDING

    app._handle_event(CancelPressed())

    assert app._state == State.IDLE
    mocks["recorder"].cancel.assert_called_once()
    mocks["transcribe"].assert_not_called()
    mocks["inject_text"].assert_not_called()


def test_state_machine_max_duration_triggers_transcribe(app, mocks):
    from whisperlite.app import HotkeyPressed, MaxDurationReached, State

    _make_idle(app)
    app._handle_event(HotkeyPressed())

    app._handle_event(MaxDurationReached())

    assert app._state == State.IDLE
    mocks["transcribe"].assert_called_once()
    mocks["inject_text"].assert_called_once()


def test_worker_loop_catches_whisperlite_error(app, mocker):
    from whisperlite.app import HotkeyPressed, ShutdownRequested, State

    mocker.patch.object(
        app, "_handle_event", side_effect=TranscribeError("bad model")
    )
    _make_idle(app)
    app._queue.put(HotkeyPressed())
    app._queue.put(ShutdownRequested())

    app._worker_loop()

    assert app._state == State.ERROR
    assert "bad model" in (app._last_error or "")


def test_worker_loop_catches_unexpected_exception(app, mocker):
    from whisperlite.app import HotkeyPressed, ShutdownRequested, State

    mocker.patch.object(
        app, "_handle_event", side_effect=RuntimeError("boom")
    )
    _make_idle(app)
    app._queue.put(HotkeyPressed())
    app._queue.put(ShutdownRequested())

    app._worker_loop()

    assert app._state == State.ERROR
    assert "boom" in (app._last_error or "")


def test_worker_recovers_from_error_state_on_next_event(app, mocks):
    from whisperlite.app import HotkeyPressed, State

    app._enter_error_state("previous failure", exc_info=False)
    assert app._state == State.ERROR

    app._handle_event(HotkeyPressed())

    assert app._state == State.RECORDING
    assert app._last_error is None
    mocks["recorder"].start.assert_called_once()


def test_shutdown_protocol_runs_in_order(app, mocks):
    from whisperlite.app import HotkeyPressed, State

    call_order: list[str] = []
    mocks["cancel_listener"].stop.side_effect = lambda: call_order.append(
        "cancel_listener"
    )
    mocks["recorder"].cancel.side_effect = lambda: call_order.append("recorder")
    mocks["hotkey_manager"].stop.side_effect = lambda: call_order.append(
        "hotkey_manager"
    )

    _make_idle(app)
    app._hotkey_manager = mocks["hotkey_manager"]
    app._handle_event(HotkeyPressed())
    mocks["recorder"].is_recording = True
    assert app._state == State.RECORDING

    worker_stopped = threading.Event()

    def _fake_worker() -> None:
        worker_stopped.wait(timeout=2.0)

    app._worker_thread = threading.Thread(target=_fake_worker, daemon=True)
    app._worker_thread.start()
    worker_stopped.set()

    app.shutdown()

    assert call_order == ["cancel_listener", "recorder", "hotkey_manager"]
    assert app._shutting_down is True
    assert app._hotkey_manager is None


def test_hotkey_pressed_in_initializing_state_is_ignored(app, mocks):
    from whisperlite.app import HotkeyPressed, State

    assert app._state == State.INITIALIZING
    app._handle_event(HotkeyPressed())

    assert app._state == State.INITIALIZING
    mocks["recorder"].start.assert_not_called()
    mocks["transcribe"].assert_not_called()


def test_post_launch_init_with_cached_model_transitions_to_idle(
    app, mocks, mocker
):
    from whisperlite.app import State

    mocker.patch.object(app, "_probe_microphone")
    mocker.patch.object(app, "_trigger_accessibility_prompt")
    mocks["is_model_cached"].return_value = True

    app.post_launch_init()

    assert app._state == State.IDLE
    mocks["warmup"].assert_called_once_with("fake/model", "en")


def test_post_launch_init_with_uncached_model_starts_download(
    app, mocks, mocker
):
    from whisperlite.app import State

    mocker.patch.object(app, "_probe_microphone")
    mocker.patch.object(app, "_trigger_accessibility_prompt")
    mocks["is_model_cached"].return_value = False

    app.post_launch_init()

    assert app._state == State.DOWNLOADING
    assert app._download_thread is not None
    app._download_cancelled.set()
    app._download_thread.join(timeout=2.0)


def test_post_launch_init_mic_probe_failure_disables_app(app, mocks, mocker):
    from whisperlite.app import State

    mocker.patch.object(
        app, "_probe_microphone", side_effect=RuntimeError("no mic")
    )

    app.post_launch_init()

    assert app._state == State.DISABLED
    assert "Microphone" in (app._last_error or "")


def test_post_launch_init_hotkey_permission_failure_disables_app(
    app, mocks, mocker
):
    from whisperlite.app import State

    mocker.patch.object(app, "_probe_microphone")
    mocker.patch.object(app, "_trigger_accessibility_prompt")
    mocks["is_model_cached"].return_value = True

    hotkey_mock = mocker.patch("whisperlite.app.HotkeyManager")
    hotkey_instance = MagicMock()
    hotkey_instance.start.side_effect = WhisperlitePermissionError("no input mon")
    hotkey_mock.return_value = hotkey_instance

    app.post_launch_init()

    assert app._state == State.DISABLED


def test_model_ready_event_transitions_downloading_to_idle(app, mocks):
    from whisperlite.app import ModelReady, State

    app._set_state(State.DOWNLOADING, title="D")
    app._handle_event(ModelReady())

    assert app._state == State.IDLE


def test_model_download_failed_event_disables_app(app, mocks):
    from whisperlite.app import ModelDownloadFailed, State

    app._set_state(State.DOWNLOADING, title="D")
    app._handle_event(ModelDownloadFailed(error="404"))

    assert app._state == State.DISABLED
    assert "404" in (app._last_error or "")


def test_play_start_sound_called_on_enter_recording(mocks, fake_config):
    from dataclasses import replace
    from whisperlite.app import HotkeyPressed, State, WhisperliteApp

    cfg = replace(fake_config, sound=replace(fake_config.sound, enabled=True))
    instance = WhisperliteApp(cfg)
    try:
        instance._set_state(State.IDLE, icon=_DEFAULT_IDLE_ICON)
        instance._handle_event(HotkeyPressed())
        mocks["play"].assert_any_call(cfg.sound.start_path)
    finally:
        if instance._max_duration_timer is not None:
            instance._max_duration_timer.cancel()


def test_play_stop_sound_called_on_exit_recording(mocks, fake_config):
    from dataclasses import replace
    from whisperlite.app import HotkeyPressed, State, WhisperliteApp

    cfg = replace(fake_config, sound=replace(fake_config.sound, enabled=True))
    instance = WhisperliteApp(cfg)
    try:
        instance._set_state(State.IDLE, icon=_DEFAULT_IDLE_ICON)
        instance._handle_event(HotkeyPressed())  # -> RECORDING
        mocks["play"].reset_mock()
        instance._handle_event(HotkeyPressed())  # -> IDLE via transcribe+inject
        mocks["play"].assert_any_call(cfg.sound.stop_path)
    finally:
        if instance._max_duration_timer is not None:
            instance._max_duration_timer.cancel()


def test_sound_not_played_when_disabled(app, mocks):
    from whisperlite.app import HotkeyPressed, State

    # fake_config fixture already disables sound
    _make_idle(app)
    app._handle_event(HotkeyPressed())
    app._handle_event(HotkeyPressed())
    mocks["play"].assert_not_called()


def test_escape_during_recording_cancels_cleanly(mocks, fake_config):
    from dataclasses import replace
    from whisperlite.app import CancelPressed, HotkeyPressed, State, WhisperliteApp

    cfg = replace(fake_config, sound=replace(fake_config.sound, enabled=True))
    instance = WhisperliteApp(cfg)
    try:
        instance._set_state(State.IDLE, icon=_DEFAULT_IDLE_ICON)
        instance._handle_event(HotkeyPressed())
        assert instance._state == State.RECORDING
        mocks["play"].reset_mock()

        instance._handle_event(CancelPressed())

        assert instance._state == State.IDLE
        mocks["recorder"].cancel.assert_called_once()
        mocks["transcribe"].assert_not_called()
        mocks["inject_text"].assert_not_called()
        mocks["play"].assert_any_call(cfg.sound.stop_path)
        mocks["cancel_listener"].stop.assert_called()
    finally:
        if instance._max_duration_timer is not None:
            instance._max_duration_timer.cancel()


def test_escape_during_transcribing_aborts_before_inject(app, mocks):
    from whisperlite.app import CancelPressed, HotkeyPressed, State

    # Simulate Escape landing during transcribe(): the mock sets the flag.
    def _transcribe_and_flag(*args, **kwargs):
        app._cancel_requested = True
        return "hello world"

    mocks["transcribe"].side_effect = _transcribe_and_flag

    _make_idle(app)
    app._handle_event(HotkeyPressed())
    assert app._state == State.RECORDING
    app._handle_event(HotkeyPressed())  # triggers finish

    assert app._state == State.IDLE
    mocks["transcribe"].assert_called_once()
    mocks["inject_text"].assert_not_called()


def test_escape_after_drain_before_transcribe(app, mocks):
    from whisperlite.app import HotkeyPressed, State

    def _drain_and_flag(*args, **kwargs):
        # Simulate the cancel listener's async callback setting the flag
        # directly on the app (which is what _on_cancel_pressed does).
        app._cancel_requested = True
        return b"fakeaudio"

    mocks["recorder"].stop_and_drain.side_effect = _drain_and_flag

    _make_idle(app)
    app._handle_event(HotkeyPressed())
    assert app._state == State.RECORDING
    app._handle_event(HotkeyPressed())

    assert app._state == State.IDLE
    mocks["transcribe"].assert_not_called()
    mocks["inject_text"].assert_not_called()


def test_escape_before_drain_skips_everything(app, mocks):
    from whisperlite.app import CancelPressed, HotkeyPressed, State

    _make_idle(app)
    app._handle_event(HotkeyPressed())
    assert app._state == State.RECORDING
    # Simulate: cancel arrives after queue-based hotkey, before finish runs.
    # We set the flag directly (the queue handling is single-threaded in tests).
    app._cancel_requested = True
    app._handle_event(HotkeyPressed())  # triggers finish, which sees the flag

    assert app._state == State.IDLE
    mocks["recorder"].stop_and_drain.assert_not_called()
    mocks["transcribe"].assert_not_called()
    mocks["inject_text"].assert_not_called()


def test_escape_during_idle_is_noop(app, mocks):
    from whisperlite.app import CancelPressed, State

    _make_idle(app)
    app._handle_event(CancelPressed())

    assert app._state == State.IDLE
    mocks["recorder"].cancel.assert_not_called()
    mocks["transcribe"].assert_not_called()


def test_escape_during_initializing_is_noop(app, mocks):
    from whisperlite.app import CancelPressed, State

    assert app._state == State.INITIALIZING
    app._handle_event(CancelPressed())

    assert app._state == State.INITIALIZING


def test_escape_during_downloading_is_noop(app, mocks):
    from whisperlite.app import CancelPressed, State

    app._set_state(State.DOWNLOADING, title="D")
    app._handle_event(CancelPressed())

    assert app._state == State.DOWNLOADING


def test_double_escape_press_is_idempotent(app, mocks):
    from whisperlite.app import CancelPressed, HotkeyPressed, State

    _make_idle(app)
    app._handle_event(HotkeyPressed())
    app._handle_event(CancelPressed())
    assert app._state == State.IDLE
    # Second escape must be a clean no-op.
    app._handle_event(CancelPressed())
    assert app._state == State.IDLE
    mocks["recorder"].cancel.assert_called_once()  # still just the first one


def test_abort_to_idle_invokes_all_cleanup_hooks(app, mocks):
    from whisperlite.app import HotkeyPressed, State

    _make_idle(app)
    app._handle_event(HotkeyPressed())
    timer_before = app._max_duration_timer
    assert timer_before is not None

    app._abort_to_idle()

    assert app._state == State.IDLE
    assert app._cancel_requested is False
    assert app._max_duration_timer is None
    assert app._recording_started_at is None
    assert app._cancel_listener is None
    mocks["recorder"].cancel.assert_called_once()
    mocks["cancel_listener"].stop.assert_called()


def test_cancel_listener_alive_through_transcribe(app, mocks):
    from whisperlite.app import HotkeyPressed, State

    observed: dict[str, object] = {}

    def _check_during_transcribe(*args, **kwargs):
        # During transcribe, the cancel listener must still be attached to
        # the app (not torn down at the start of finish anymore).
        observed["listener_attached"] = app._cancel_listener is not None
        observed["listener_stop_count"] = mocks["cancel_listener"].stop.call_count
        return "hello world"

    mocks["transcribe"].side_effect = _check_during_transcribe

    _make_idle(app)
    app._handle_event(HotkeyPressed())
    app._handle_event(HotkeyPressed())

    assert observed["listener_attached"] is True
    assert observed["listener_stop_count"] == 0
    # After inject + return to idle, the listener IS stopped exactly once.
    assert mocks["cancel_listener"].stop.call_count == 1
    assert app._cancel_listener is None


def test_on_open_config_uses_effective_path_and_ensures_file(app, mocker, tmp_path):
    target = tmp_path / "whisperlite.toml"
    get_path_mock = mocker.patch(
        "whisperlite.app.get_effective_config_path", return_value=target
    )
    ensure_mock = mocker.patch("whisperlite.app.ensure_config_exists")
    run_mock = mocker.patch("whisperlite.app.subprocess.run")

    app._on_open_config(None)

    get_path_mock.assert_called_once_with()
    ensure_mock.assert_called_once_with(target)
    # ensure_config_exists must be called before subprocess.run
    assert ensure_mock.call_count == 1
    run_mock.assert_called_once()
    args, _kwargs = run_mock.call_args
    assert args[0] == ["open", str(target)]
