from __future__ import annotations

import logging
from unittest.mock import MagicMock

import numpy as np
import pytest

from whisperlite import audio as audio_mod
from whisperlite.errors import AudioDeviceError, AudioStreamError


class _FakeCallbackStop(Exception):
    pass


class _FakeCallbackFlags:
    def __init__(self, input_overflow: bool = False) -> None:
        self.input_overflow = input_overflow

    def __bool__(self) -> bool:
        return self.input_overflow

    def __str__(self) -> str:
        return f"input_overflow={self.input_overflow}"


@pytest.fixture
def mock_sd(mocker):
    mock = mocker.patch.object(audio_mod, "sd")
    mock.CallbackStop = _FakeCallbackStop
    mock.CallbackFlags = _FakeCallbackFlags

    stream_instance = MagicMock()
    stream_instance.active = True
    mock.InputStream.return_value = stream_instance

    mock.query_devices.return_value = {
        "name": "Default Mic",
        "max_input_channels": 2,
        "default_samplerate": 48000.0,
    }
    return mock


def _make_chunk(value: int, n: int = 1024) -> np.ndarray:
    return np.full((n, 1), value, dtype=np.int16)


def test_list_input_devices_returns_input_only(mock_sd) -> None:
    mock_sd.query_devices.return_value = [
        {"name": "Mic", "max_input_channels": 2},
        {"name": "Speakers", "max_input_channels": 0},
        {"name": "Headset", "max_input_channels": 1},
    ]
    result = audio_mod.list_input_devices()
    assert len(result) == 2
    assert all(d["max_input_channels"] > 0 for d in result)
    assert [d["name"] for d in result] == ["Mic", "Headset"]


def test_get_default_input_returns_dict(mock_sd) -> None:
    mock_sd.query_devices.return_value = {
        "name": "Default Mic",
        "max_input_channels": 1,
    }
    result = audio_mod.get_default_input()
    assert result is not None
    assert result["name"] == "Default Mic"
    mock_sd.query_devices.assert_called_with(kind="input")


def test_get_default_input_returns_none_when_no_input(mock_sd) -> None:
    mock_sd.query_devices.side_effect = RuntimeError("no device")
    assert audio_mod.get_default_input() is None


def test_get_default_input_returns_none_when_zero_input_channels(mock_sd) -> None:
    mock_sd.query_devices.return_value = {
        "name": "Output Only",
        "max_input_channels": 0,
    }
    assert audio_mod.get_default_input() is None


def test_recorder_start_raises_when_no_input_device(mock_sd) -> None:
    mock_sd.query_devices.side_effect = RuntimeError("no device")
    recorder = audio_mod.AudioRecorder()
    with pytest.raises(AudioDeviceError, match="no input device available"):
        recorder.start()


def test_recorder_start_raises_when_inputstream_fails(mock_sd) -> None:
    mock_sd.InputStream.side_effect = RuntimeError("PortAudio boom")
    recorder = audio_mod.AudioRecorder()
    with pytest.raises(AudioDeviceError, match="PortAudio boom"):
        recorder.start()
    assert recorder._stream is None


def test_recorder_start_then_drain_returns_int16_array(mock_sd) -> None:
    recorder = audio_mod.AudioRecorder()
    recorder.start()

    chunk = _make_chunk(42, n=1024)
    recorder._callback(chunk, 1024, None, _FakeCallbackFlags())

    mock_sd.InputStream.return_value.active = False
    result = recorder.stop_and_drain()

    assert result.dtype == np.int16
    assert result.shape == (1024,)
    assert np.all(result == 42)


def test_recorder_drain_concatenates_multiple_chunks(mock_sd) -> None:
    recorder = audio_mod.AudioRecorder()
    recorder.start()

    for value in (1, 2, 3):
        recorder._callback(_make_chunk(value, n=512), 512, None, _FakeCallbackFlags())

    mock_sd.InputStream.return_value.active = False
    result = recorder.stop_and_drain()

    assert result.shape == (1536,)
    assert np.all(result[:512] == 1)
    assert np.all(result[512:1024] == 2)
    assert np.all(result[1024:] == 3)


def test_max_seconds_cap_triggers_callback_stop(mock_sd) -> None:
    recorder = audio_mod.AudioRecorder(sample_rate=16000, max_seconds=1)
    recorder.start()

    chunk = _make_chunk(7, n=8000)
    recorder._callback(chunk, 8000, None, _FakeCallbackFlags())
    assert recorder.max_duration_reached is False

    with pytest.raises(_FakeCallbackStop):
        recorder._callback(chunk, 8000, None, _FakeCallbackFlags())

    assert recorder.max_duration_reached is True


def test_input_overflow_logs_warning_does_not_raise(mock_sd, caplog) -> None:
    recorder = audio_mod.AudioRecorder()
    recorder.start()

    with caplog.at_level(logging.WARNING, logger="whisperlite.audio"):
        recorder._callback(
            _make_chunk(5, n=256), 256, None, _FakeCallbackFlags(input_overflow=True)
        )

    assert any("overflow" in rec.message.lower() for rec in caplog.records)


def test_stream_error_flag_raises_on_drain(mock_sd) -> None:
    recorder = audio_mod.AudioRecorder()
    recorder.start()
    recorder._stream_error = "stream aborted, possibly device unplug"

    mock_sd.InputStream.return_value.active = False
    with pytest.raises(AudioStreamError, match="stream aborted"):
        recorder.stop_and_drain()


def test_double_start_is_idempotent_and_warns(mock_sd, caplog) -> None:
    recorder = audio_mod.AudioRecorder()
    recorder.start()

    with caplog.at_level(logging.WARNING, logger="whisperlite.audio"):
        recorder.start()

    assert any("already recording" in rec.message for rec in caplog.records)
    assert mock_sd.InputStream.call_count == 1


def test_drain_when_not_recording_returns_empty(mock_sd) -> None:
    recorder = audio_mod.AudioRecorder()
    result = recorder.stop_and_drain()
    assert result.dtype == np.int16
    assert result.shape == (0,)


def test_cancel_discards_buffer(mock_sd) -> None:
    recorder = audio_mod.AudioRecorder()
    recorder.start()
    recorder._callback(_make_chunk(9, n=1024), 1024, None, _FakeCallbackFlags())

    mock_sd.InputStream.return_value.active = False
    recorder.cancel()

    result = recorder.stop_and_drain()
    assert result.shape == (0,)
