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


def test_inject_text_calls_clearContents_then_setString(
    mock_pb, mock_cg, mock_nspbitem
) -> None:
    inject_mod.inject_text("hello")
    calls = [c[0] for c in mock_pb.method_calls]
    # clearContents must come before setString_forType_
    assert "clearContents" in calls
    assert "setString_forType_" in calls
    assert calls.index("clearContents") < calls.index("setString_forType_")
    mock_pb.setString_forType_.assert_any_call("hello", inject_mod.NSPasteboardTypeString)


def test_inject_text_synthesizes_cmd_v(mock_pb, mock_cg, mock_nspbitem) -> None:
    created, set_flags, post = mock_cg
    inject_mod.inject_text("hi")
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
    inject_mod.inject_text("hi", paste_delay_ms=250)
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
    inject_mod.inject_text("hi")
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
        inject_mod.inject_text("hi")
    mock_pb.writeObjects_.assert_not_called()
    assert any("skipping restore" in r.message for r in caplog.records)


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

    inject_mod.inject_text("hi")

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
        inject_mod.inject_text("hi")
