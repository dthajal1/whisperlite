from __future__ import annotations

import logging

import pytest
from pynput import keyboard
from pynput.keyboard import Key

from whisperlite.errors import ConfigError, WhisperlitePermissionError
from whisperlite.hotkey import CancelListener, HotkeyManager


class _FakeClock:
    def __init__(self, values: list[float]) -> None:
        self._values = list(values)
        self._last = values[0] if values else 0.0

    def __call__(self) -> float:
        if self._values:
            self._last = self._values.pop(0)
        return self._last


@pytest.fixture
def fake_listener(mocker):
    """Patch whisperlite.hotkey.keyboard.Listener; expose on_press/on_release."""
    captured: dict[str, object] = {}
    instance = mocker.MagicMock()
    instance.running = False

    def _factory(*args, **kwargs):
        captured["on_press"] = kwargs.get("on_press")
        captured["on_release"] = kwargs.get("on_release")
        captured["instance"] = instance
        return instance

    mock = mocker.patch(
        "whisperlite.hotkey.keyboard.Listener", side_effect=_factory
    )
    return mock, instance, captured


@pytest.fixture
def fake_clock(mocker):
    """Patch whisperlite.hotkey.time.monotonic with a controllable clock."""
    clock = _FakeClock([0.0])
    mocker.patch("whisperlite.hotkey.time.monotonic", side_effect=clock)
    return clock


def _make_manager(fake_listener, fake_clock, on_press_cb=None, modifier="<alt>"):
    calls: list[int] = []

    def _cb() -> None:
        calls.append(1)

    mgr = HotkeyManager(
        modifier=modifier,
        double_tap_window_ms=400,
        on_record_pressed=on_press_cb or _cb,
    )
    mgr.start()
    return mgr, calls, fake_listener[2]


def test_valid_double_tap_fires_callback(fake_listener, fake_clock):
    fake_clock._values = [
        1.00,  # press 1
        1.05,  # release 1 (hold check)
        1.05,  # release 1 (now)
        1.30,  # press 2
        1.35,  # release 2 (hold check)
        1.35,  # release 2 (now)
    ]
    mgr, calls, cap = _make_manager(fake_listener, fake_clock)
    cap["on_press"](Key.alt)
    cap["on_release"](Key.alt)
    cap["on_press"](Key.alt)
    cap["on_release"](Key.alt)
    assert calls == [1]


def test_double_tap_outside_window_does_not_fire(fake_listener, fake_clock):
    fake_clock._values = [1.00, 1.05, 1.05, 2.00, 2.05, 2.05]
    mgr, calls, cap = _make_manager(fake_listener, fake_clock)
    cap["on_press"](Key.alt)
    cap["on_release"](Key.alt)
    cap["on_press"](Key.alt)
    cap["on_release"](Key.alt)
    assert calls == []


def test_single_tap_does_not_fire(fake_listener, fake_clock):
    fake_clock._values = [1.00, 1.05, 1.05]
    mgr, calls, cap = _make_manager(fake_listener, fake_clock)
    cap["on_press"](Key.alt)
    cap["on_release"](Key.alt)
    assert calls == []


def test_three_taps_fires_once_then_starts_counting_again(
    fake_listener, fake_clock
):
    fake_clock._values = [
        1.00, 1.05, 1.05,  # tap 1
        1.20, 1.25, 1.25,  # tap 2 -> fires
        1.40, 1.45, 1.45,  # tap 3 -> just a first tap again
    ]
    mgr, calls, cap = _make_manager(fake_listener, fake_clock)
    for _ in range(3):
        cap["on_press"](Key.alt)
        cap["on_release"](Key.alt)
    assert calls == [1]


def test_hold_alt_does_not_count_as_tap(fake_listener, fake_clock):
    fake_clock._values = [
        1.00,         # press 1
        1.50,         # release 1 hold check (>300ms -> disqualified)
        1.70,         # press 2
        1.75, 1.75,   # release 2 hold check, now
    ]
    mgr, calls, cap = _make_manager(fake_listener, fake_clock)
    cap["on_press"](Key.alt)
    cap["on_release"](Key.alt)
    cap["on_press"](Key.alt)
    cap["on_release"](Key.alt)
    assert calls == []


def test_alt_plus_key_is_chord_not_tap(fake_listener, fake_clock):
    fake_clock._values = [1.00, 1.05]
    mgr, calls, cap = _make_manager(fake_listener, fake_clock)
    cap["on_press"](Key.alt)
    cap["on_press"](keyboard.KeyCode.from_char("c"))
    cap["on_release"](keyboard.KeyCode.from_char("c"))
    cap["on_release"](Key.alt)
    assert calls == []
    assert mgr._last_complete_tap_time is None


def test_left_and_right_alt_are_treated_as_same_modifier(
    fake_listener, fake_clock
):
    fake_clock._values = [1.00, 1.05, 1.05, 1.30, 1.35, 1.35]
    mgr, calls, cap = _make_manager(fake_listener, fake_clock)
    cap["on_press"](Key.alt_l)
    cap["on_release"](Key.alt_l)
    cap["on_press"](Key.alt_r)
    cap["on_release"](Key.alt_r)
    assert calls == [1]


def test_different_modifier_does_not_count(fake_listener, fake_clock):
    fake_clock._values = [1.00, 1.05, 1.05, 1.30, 1.35, 1.35]
    mgr, calls, cap = _make_manager(fake_listener, fake_clock)
    cap["on_press"](Key.shift)
    cap["on_release"](Key.shift)
    cap["on_press"](Key.shift)
    cap["on_release"](Key.shift)
    assert calls == []


def test_chord_interference_does_not_leave_stale_state(
    fake_listener, fake_clock
):
    fake_clock._values = [
        1.00,                # press alt (chord start)
        # release alt after chord: no hold-check read path needed since chord disqualifies
        2.00,                # press alt (tap 1)
        2.05, 2.05,          # release alt tap 1
        2.30,                # press alt (tap 2)
        2.35, 2.35,          # release alt tap 2 -> fires
    ]
    mgr, calls, cap = _make_manager(fake_listener, fake_clock)
    # chord
    cap["on_press"](Key.alt)
    cap["on_press"](keyboard.KeyCode.from_char("c"))
    cap["on_release"](keyboard.KeyCode.from_char("c"))
    cap["on_release"](Key.alt)
    # clean double-tap
    cap["on_press"](Key.alt)
    cap["on_release"](Key.alt)
    cap["on_press"](Key.alt)
    cap["on_release"](Key.alt)
    assert calls == [1]


def test_key_repeat_is_ignored(fake_listener, fake_clock):
    fake_clock._values = [
        1.00,              # initial press
        1.05, 1.05,        # release 1
        1.20,              # press 2
        1.25, 1.25,        # release 2 -> fires
    ]
    mgr, calls, cap = _make_manager(fake_listener, fake_clock)
    cap["on_press"](Key.alt)
    cap["on_press"](Key.alt)  # key-repeat, should be ignored
    cap["on_press"](Key.alt)  # key-repeat, should be ignored
    cap["on_release"](Key.alt)
    cap["on_press"](Key.alt)
    cap["on_release"](Key.alt)
    assert calls == [1]


def test_callback_exception_is_swallowed(fake_listener, fake_clock, caplog):
    fake_clock._values = [1.00, 1.05, 1.05, 1.30, 1.35, 1.35]

    def boom() -> None:
        raise RuntimeError("kaboom")

    mgr, _calls, cap = _make_manager(
        fake_listener, fake_clock, on_press_cb=boom
    )
    with caplog.at_level(logging.ERROR, logger="whisperlite.hotkey"):
        cap["on_press"](Key.alt)
        cap["on_release"](Key.alt)
        cap["on_press"](Key.alt)
        cap["on_release"](Key.alt)

    assert any("kaboom" in rec.message for rec in caplog.records)


def test_invalid_modifier_raises_config_error(fake_listener, fake_clock):
    mgr = HotkeyManager(
        modifier="<tab>",
        double_tap_window_ms=400,
        on_record_pressed=lambda: None,
    )
    with pytest.raises(ConfigError, match="hotkey.record must be one of"):
        mgr.start()

    mgr2 = HotkeyManager(
        modifier="<ctrl>+<alt>+<space>",
        double_tap_window_ms=400,
        on_record_pressed=lambda: None,
    )
    with pytest.raises(ConfigError):
        mgr2.start()


def test_start_failure_raises_permission_error(mocker, fake_clock):
    mocker.patch(
        "whisperlite.hotkey.keyboard.Listener",
        side_effect=OSError("permission denied"),
    )
    mgr = HotkeyManager(
        modifier="<alt>",
        double_tap_window_ms=400,
        on_record_pressed=lambda: None,
    )
    with pytest.raises(WhisperlitePermissionError):
        mgr.start()


def test_stop_is_idempotent(fake_listener, fake_clock):
    mgr, _, _ = _make_manager(fake_listener, fake_clock)
    instance = fake_listener[1]
    mgr.stop()
    mgr.stop()
    assert instance.stop.call_count == 1


def test_is_running_reflects_listener_state(fake_listener, fake_clock):
    _mock, instance, _ = fake_listener
    mgr = HotkeyManager(
        modifier="<alt>",
        double_tap_window_ms=400,
        on_record_pressed=lambda: None,
    )
    assert mgr.is_running is False
    mgr.start()
    instance.running = True
    assert mgr.is_running is True
    instance.running = False
    mgr.stop()
    assert mgr.is_running is False


# --- CancelListener tests (unchanged) ---


@pytest.fixture
def mock_cancel_listener(mocker):
    mock = mocker.patch("whisperlite.hotkey.keyboard.Listener")
    instance = mocker.MagicMock()
    instance.running = False
    mock.return_value = instance
    return mock, instance


def test_cancel_listener_calls_callback_on_escape(mock_cancel_listener):
    mock, _ = mock_cancel_listener
    calls: list[int] = []

    cl = CancelListener(on_cancel=lambda: calls.append(1))
    cl.start()

    on_press = mock.call_args.kwargs["on_press"]
    on_press(keyboard.Key.esc)
    assert calls == [1]

    on_press(keyboard.KeyCode.from_char("a"))
    assert calls == [1]


def test_cancel_listener_start_creates_listener(mock_cancel_listener):
    mock, _ = mock_cancel_listener
    cl = CancelListener(on_cancel=lambda: None)
    cl.start()
    mock.assert_called_once()
    assert "on_press" in mock.call_args.kwargs


def test_cancel_listener_stop_calls_underlying_stop_and_join(
    mock_cancel_listener,
):
    _, instance = mock_cancel_listener
    cl = CancelListener(on_cancel=lambda: None)
    cl.start()
    cl.stop()
    instance.stop.assert_called_once()
    instance.join.assert_called_once()


def test_cancel_listener_callback_returns_false_after_escape(
    mock_cancel_listener,
):
    mock, _ = mock_cancel_listener
    cl = CancelListener(on_cancel=lambda: None)
    cl.start()

    on_press = mock.call_args.kwargs["on_press"]
    assert on_press(keyboard.Key.esc) is False
    assert on_press(keyboard.KeyCode.from_char("a")) is None


def test_cancel_listener_stop_is_idempotent(mock_cancel_listener):
    _, instance = mock_cancel_listener
    cl = CancelListener(on_cancel=lambda: None)
    cl.start()
    cl.stop()
    cl.stop()
    assert instance.stop.call_count == 1
