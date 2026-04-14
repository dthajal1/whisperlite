from __future__ import annotations

import pytest

from whisperlite import inject as inject_mod
from whisperlite.errors import InjectError


@pytest.fixture(autouse=True)
def no_sleep(mocker):
    """Patch time.sleep so tests don't actually wait."""
    return mocker.patch.object(inject_mod.time, "sleep")


@pytest.fixture
def mock_pb(mocker):
    pb = mocker.MagicMock(name="pasteboard")
    pb.changeCount.return_value = 1
    pb.pasteboardItems.return_value = []
    fake_ns_pb = mocker.MagicMock(name="NSPasteboard")
    fake_ns_pb.generalPasteboard.return_value = pb
    mocker.patch.object(inject_mod, "NSPasteboard", fake_ns_pb)
    return pb


@pytest.fixture
def mock_workspace(mocker):
    ws = mocker.MagicMock(name="workspace")
    fake_ns_ws = mocker.MagicMock(name="NSWorkspace")
    fake_ns_ws.sharedWorkspace.return_value = ws
    mocker.patch.object(inject_mod, "NSWorkspace", fake_ns_ws)
    return ws


@pytest.fixture
def mock_running_app(mocker):
    app = mocker.MagicMock(name="running_app")
    fake_cls = mocker.MagicMock(name="NSRunningApplication")
    fake_cls.runningApplicationWithProcessIdentifier_.return_value = app
    mocker.patch.object(inject_mod, "NSRunningApplication", fake_cls)
    return fake_cls, app


@pytest.fixture
def mock_cg(mocker):
    created = mocker.patch.object(
        inject_mod, "CGEventCreateKeyboardEvent", return_value=mocker.MagicMock()
    )
    set_flags = mocker.patch.object(inject_mod, "CGEventSetFlags")
    post = mocker.patch.object(inject_mod, "CGEventPost")
    return created, set_flags, post


@pytest.fixture
def mock_nspbitem(mocker):
    new_items: list = []

    def _alloc():
        item = mocker.MagicMock(name="new_pb_item")
        new_items.append(item)
        item.init.return_value = item
        return item

    fake_cls = mocker.MagicMock(name="NSPasteboardItem")
    fake_cls.alloc.side_effect = _alloc
    mocker.patch.object(inject_mod, "NSPasteboardItem", fake_cls)
    return new_items


def test_capture_focused_app_returns_pid(mock_workspace) -> None:
    app = mock_workspace.frontmostApplication.return_value
    app.processIdentifier.return_value = 1234
    assert inject_mod.capture_focused_app() == 1234


def test_capture_focused_app_returns_none_when_no_frontmost(mock_workspace) -> None:
    mock_workspace.frontmostApplication.return_value = None
    assert inject_mod.capture_focused_app() is None


def test_capture_focused_app_handles_pyobjc_exception_gracefully(
    mock_workspace, caplog
) -> None:
    mock_workspace.frontmostApplication.side_effect = RuntimeError("boom")
    with caplog.at_level("WARNING"):
        assert inject_mod.capture_focused_app() is None
    assert any("capture_focused_app failed" in r.message for r in caplog.records)


def test_inject_text_calls_clearContents_then_setString(
    mock_pb, mock_cg, mock_nspbitem
) -> None:
    inject_mod.inject_text("hello", target_pid=None)
    calls = [c[0] for c in mock_pb.method_calls]
    # clearContents must come before setString_forType_
    assert "clearContents" in calls
    assert "setString_forType_" in calls
    assert calls.index("clearContents") < calls.index("setString_forType_")
    mock_pb.setString_forType_.assert_any_call("hello", inject_mod.NSPasteboardTypeString)


def test_inject_text_synthesizes_cmd_v(mock_pb, mock_cg, mock_nspbitem) -> None:
    created, set_flags, post = mock_cg
    inject_mod.inject_text("hi", target_pid=None)
    assert created.call_count == 2
    # (source, keycode, down)
    assert created.call_args_list[0][0][1] == inject_mod.KEYCODE_V
    assert created.call_args_list[0][0][2] is True
    assert created.call_args_list[1][0][1] == inject_mod.KEYCODE_V
    assert created.call_args_list[1][0][2] is False
    assert post.call_count == 2
    for call in set_flags.call_args_list:
        assert call[0][1] == inject_mod.kCGEventFlagMaskCommand


def test_inject_text_sleeps_paste_delay(
    mock_pb, mock_cg, mock_nspbitem, no_sleep
) -> None:
    inject_mod.inject_text("hi", target_pid=None, paste_delay_ms=250)
    durations = [c[0][0] for c in no_sleep.call_args_list]
    assert 0.25 in durations


def test_inject_text_restores_pasteboard_when_only_own_writes_happened(
    mocker, mock_pb, mock_cg, mock_nspbitem
) -> None:
    """delta of 2 = whisperlite's own clearContents + setString; restore should run."""
    item = mocker.MagicMock()
    item.types.return_value = ["public.utf8-plain-text"]
    item.dataForType_.return_value = mocker.MagicMock(name="nsdata")
    mock_pb.pasteboardItems.return_value = [item]
    mock_pb.changeCount.side_effect = [5, 7]
    inject_mod.inject_text("hi", target_pid=None)
    mock_pb.writeObjects_.assert_called_once()


def test_inject_text_skips_restore_when_external_writes_happened(
    mocker, mock_pb, mock_cg, mock_nspbitem, caplog
) -> None:
    """delta > 2 = external interference on top of our clearContents + setString; skip restore."""
    item = mocker.MagicMock()
    item.types.return_value = ["public.utf8-plain-text"]
    item.dataForType_.return_value = mocker.MagicMock(name="nsdata")
    mock_pb.pasteboardItems.return_value = [item]
    mock_pb.changeCount.side_effect = [5, 9]
    with caplog.at_level("INFO"):
        inject_mod.inject_text("hi", target_pid=None)
    mock_pb.writeObjects_.assert_not_called()
    assert any("skipping restore" in r.message for r in caplog.records)


def test_inject_text_with_target_pid_activates_app(
    mock_pb, mock_cg, mock_nspbitem, mock_running_app, mock_workspace
) -> None:
    fake_cls, app = mock_running_app
    app.processIdentifier.return_value = 1234
    # frontmostApplication() returns an app whose PID matches target immediately,
    # so _force_activate's first poll succeeds.
    front = mock_workspace.frontmostApplication.return_value
    front.processIdentifier.return_value = 1234
    inject_mod.inject_text("hi", target_pid=1234)
    fake_cls.runningApplicationWithProcessIdentifier_.assert_called_once_with(1234)
    app.activateWithOptions_.assert_called_once_with(
        inject_mod.NSApplicationActivateIgnoringOtherApps
    )


def test_inject_text_with_gone_target_pid_raises_inject_error(
    mocker, mock_pb, mock_cg, mock_nspbitem
) -> None:
    fake_cls = mocker.MagicMock(name="NSRunningApplication")
    fake_cls.runningApplicationWithProcessIdentifier_.return_value = None
    mocker.patch.object(inject_mod, "NSRunningApplication", fake_cls)
    _, _, post = mock_cg
    with pytest.raises(InjectError, match="target app no longer exists"):
        inject_mod.inject_text("hi there", target_pid=9999)
    mock_pb.setString_forType_.assert_any_call(
        "hi there", inject_mod.NSPasteboardTypeString
    )
    post.assert_not_called()
    mock_pb.writeObjects_.assert_not_called()


def test_inject_text_with_none_target_pid_skips_activation(
    mocker, mock_pb, mock_cg, mock_nspbitem, mock_running_app
) -> None:
    fake_cls, _ = mock_running_app
    inject_mod.inject_text("hi", target_pid=None)
    fake_cls.runningApplicationWithProcessIdentifier_.assert_not_called()
    # cmd+v still sent
    created, _, post = mock_cg
    assert created.call_count == 2
    assert post.call_count == 2


def test_inject_text_snapshot_handles_multiple_pasteboard_items(
    mocker, mock_pb, mock_cg, mock_nspbitem
) -> None:
    data_a1 = mocker.MagicMock(name="data_a1")
    data_a2 = mocker.MagicMock(name="data_a2")
    data_b1 = mocker.MagicMock(name="data_b1")
    item_a = mocker.MagicMock()
    item_a.types.return_value = ["public.utf8-plain-text", "public.rtf"]
    item_a.dataForType_.side_effect = lambda t: {
        "public.utf8-plain-text": data_a1,
        "public.rtf": data_a2,
    }[t]
    item_b = mocker.MagicMock()
    item_b.types.return_value = ["public.png"]
    item_b.dataForType_.return_value = data_b1

    mock_pb.pasteboardItems.return_value = [item_a, item_b]
    mock_pb.changeCount.side_effect = [10, 11]

    inject_mod.inject_text("hi", target_pid=None)

    # Two new items rebuilt and written
    assert len(mock_nspbitem) == 2
    mock_nspbitem[0].setData_forType_.assert_any_call(data_a1, "public.utf8-plain-text")
    mock_nspbitem[0].setData_forType_.assert_any_call(data_a2, "public.rtf")
    mock_nspbitem[1].setData_forType_.assert_any_call(data_b1, "public.png")
    mock_pb.writeObjects_.assert_called_once()
    written = mock_pb.writeObjects_.call_args[0][0]
    assert len(written) == 2


def test_inject_text_unexpected_exception_wraps_as_inject_error(
    mock_pb, mock_cg, mock_nspbitem
) -> None:
    _, _, post = mock_cg
    post.side_effect = RuntimeError("cg exploded")
    with pytest.raises(InjectError, match="inject failed"):
        inject_mod.inject_text("hi", target_pid=None)


def test_force_activate_falls_back_to_applescript_when_native_blocked(
    mocker, mock_workspace
) -> None:
    app = mocker.MagicMock(name="running_app")
    app.processIdentifier.return_value = 1234
    app.localizedName.return_value = "Notes"

    wrong_front = mocker.MagicMock(name="wrong_front")
    wrong_front.processIdentifier.return_value = 9999
    right_front = mocker.MagicMock(name="right_front")
    right_front.processIdentifier.return_value = 1234

    # Poll phase: always wrong PID (simulating Sequoia block).
    # After AppleScript: returns target PID.
    front_side_effect = [wrong_front] * 10 + [right_front]
    mock_workspace.frontmostApplication.side_effect = front_side_effect

    # Make poll loop deterministic: 10 iterations at 0.05s intervals,
    # then exceed deadline on iteration 11.
    # time.monotonic is called once for `deadline = now + 0.5` and
    # then once per loop check.
    monotonic_values = [0.0]  # for deadline calc => deadline = 0.5
    for i in range(10):
        monotonic_values.append(i * 0.05)  # 0.0 .. 0.45 (all < 0.5)
    monotonic_values.append(0.5)  # fails the < deadline check
    monotonic_values.extend([1.0] * 20)  # extra, just in case
    mocker.patch.object(
        inject_mod.time, "monotonic", side_effect=monotonic_values
    )
    mocker.patch.object(inject_mod.time, "sleep")

    completed = mocker.MagicMock(returncode=0, stdout=b"", stderr=b"")
    run_mock = mocker.patch.object(
        inject_mod.subprocess, "run", return_value=completed
    )

    assert inject_mod._force_activate(app) is True
    run_mock.assert_called_once()
    args, kwargs = run_mock.call_args
    assert args[0] == [
        "osascript",
        "-e",
        'tell application "Notes" to activate',
    ]
    app.activateWithOptions_.assert_called_once_with(
        inject_mod.NSApplicationActivateIgnoringOtherApps
    )


def test_force_activate_returns_false_when_both_native_and_applescript_fail(
    mocker, mock_workspace
) -> None:
    app = mocker.MagicMock(name="running_app")
    app.processIdentifier.return_value = 1234
    app.localizedName.return_value = "Notes"

    wrong_front = mocker.MagicMock()
    wrong_front.processIdentifier.return_value = 9999
    mock_workspace.frontmostApplication.return_value = wrong_front

    monotonic_values = [0.0]
    for i in range(10):
        monotonic_values.append(i * 0.05)
    monotonic_values.extend([0.5] * 20)
    mocker.patch.object(
        inject_mod.time, "monotonic", side_effect=monotonic_values
    )
    mocker.patch.object(inject_mod.time, "sleep")

    completed = mocker.MagicMock(returncode=0, stdout=b"", stderr=b"")
    mocker.patch.object(
        inject_mod.subprocess, "run", return_value=completed
    )

    assert inject_mod._force_activate(app) is False


def test_inject_text_raises_when_activation_fully_fails(
    mocker, mock_pb, mock_cg, mock_nspbitem, mock_running_app
) -> None:
    mocker.patch("whisperlite.inject._force_activate", return_value=False)
    send = mocker.patch("whisperlite.inject._send_cmd_v")
    with pytest.raises(InjectError, match="could not bring target app to front"):
        inject_mod.inject_text("hi there", target_pid=1234)
    mock_pb.setString_forType_.assert_any_call(
        "hi there", inject_mod.NSPasteboardTypeString
    )
    send.assert_not_called()
