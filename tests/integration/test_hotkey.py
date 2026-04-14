from __future__ import annotations

import logging

import pytest

from whisperlite.errors import ConfigError, WhisperlitePermissionError
from whisperlite.hotkey import CancelListener, HotkeyManager


@pytest.fixture
def mock_global_hotkeys(mocker):
    mock = mocker.patch("whisperlite.hotkey.GlobalHotKeys")
    instance = mocker.MagicMock()
    instance.running = False
    mock.return_value = instance
    return mock, instance


@pytest.fixture
def mock_listener(mocker):
    mock = mocker.patch("whisperlite.hotkey.keyboard.Listener")
    instance = mocker.MagicMock()
    instance.running = False
    mock.return_value = instance
    return mock, instance


def test_hotkey_manager_starts_global_hotkeys_with_keyspec(mock_global_hotkeys):
    mock, instance = mock_global_hotkeys
    mgr = HotkeyManager(record_keyspec="<f5>", on_record_pressed=lambda: None)
    mgr.start()

    mock.assert_called_once()
    (keymap,), _ = mock.call_args
    assert "<f5>" in keymap
    instance.start.assert_called_once()


def test_hotkey_manager_callback_invokes_user_callback(mock_global_hotkeys):
    mock, _ = mock_global_hotkeys
    calls: list[int] = []

    mgr = HotkeyManager(
        record_keyspec="<f5>", on_record_pressed=lambda: calls.append(1)
    )
    mgr.start()

    (keymap,), _ = mock.call_args
    keymap["<f5>"]()
    assert calls == [1]


def test_hotkey_manager_callback_swallows_exceptions(
    mock_global_hotkeys, caplog
):
    mock, _ = mock_global_hotkeys

    def boom() -> None:
        raise RuntimeError("kaboom")

    mgr = HotkeyManager(record_keyspec="<f5>", on_record_pressed=boom)
    mgr.start()

    (keymap,), _ = mock.call_args
    with caplog.at_level(logging.ERROR, logger="whisperlite.hotkey"):
        keymap["<f5>"]()

    assert any("kaboom" in rec.message for rec in caplog.records)


def test_hotkey_manager_invalid_keyspec_raises_config_error(mocker):
    mocker.patch(
        "whisperlite.hotkey.GlobalHotKeys",
        side_effect=ValueError("bad keyspec"),
    )
    mgr = HotkeyManager(record_keyspec="<<<>>>", on_record_pressed=lambda: None)
    with pytest.raises(ConfigError, match="invalid hotkey keyspec"):
        mgr.start()


def test_hotkey_manager_start_failure_raises_permission_error(
    mock_global_hotkeys,
):
    _, instance = mock_global_hotkeys
    instance.start.side_effect = OSError("permission denied")

    mgr = HotkeyManager(record_keyspec="<f5>", on_record_pressed=lambda: None)
    with pytest.raises(WhisperlitePermissionError):
        mgr.start()


def test_hotkey_manager_stop_is_idempotent(mock_global_hotkeys):
    _, instance = mock_global_hotkeys
    mgr = HotkeyManager(record_keyspec="<f5>", on_record_pressed=lambda: None)
    mgr.start()
    mgr.stop()
    mgr.stop()
    assert instance.stop.call_count == 1


def test_hotkey_manager_is_running_reflects_listener_state(mock_global_hotkeys):
    _, instance = mock_global_hotkeys
    mgr = HotkeyManager(record_keyspec="<f5>", on_record_pressed=lambda: None)
    assert mgr.is_running is False
    mgr.start()
    instance.running = True
    assert mgr.is_running is True
    instance.running = False
    mgr.stop()
    assert mgr.is_running is False


def test_cancel_listener_calls_callback_on_escape(mock_listener):
    from pynput import keyboard

    mock, _ = mock_listener
    calls: list[int] = []

    cl = CancelListener(on_cancel=lambda: calls.append(1))
    cl.start()

    on_press = mock.call_args.kwargs["on_press"]
    on_press(keyboard.Key.esc)
    assert calls == [1]

    on_press(keyboard.KeyCode.from_char("a"))
    assert calls == [1]


def test_cancel_listener_start_creates_listener(mock_listener):
    mock, _ = mock_listener
    cl = CancelListener(on_cancel=lambda: None)
    cl.start()
    mock.assert_called_once()
    assert "on_press" in mock.call_args.kwargs


def test_cancel_listener_stop_calls_underlying_stop_and_join(mock_listener):
    _, instance = mock_listener
    cl = CancelListener(on_cancel=lambda: None)
    cl.start()
    cl.stop()
    instance.stop.assert_called_once()
    instance.join.assert_called_once()


def test_cancel_listener_callback_returns_false_after_escape(mock_listener):
    from pynput import keyboard

    mock, _ = mock_listener
    cl = CancelListener(on_cancel=lambda: None)
    cl.start()

    on_press = mock.call_args.kwargs["on_press"]
    assert on_press(keyboard.Key.esc) is False
    assert on_press(keyboard.KeyCode.from_char("a")) is None


def test_cancel_listener_stop_is_idempotent(mock_listener):
    _, instance = mock_listener
    cl = CancelListener(on_cancel=lambda: None)
    cl.start()
    cl.stop()
    cl.stop()
    assert instance.stop.call_count == 1
