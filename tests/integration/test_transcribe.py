from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from whisperlite import transcribe as transcribe_mod
from whisperlite.errors import ModelDownloadError, ModelLoadError, TranscribeError

MODEL = "mlx-community/whisper-small-mlx"
LANG = "en"


def test_is_model_cached_returns_true_when_cached(mocker) -> None:
    mocker.patch.object(
        transcribe_mod.huggingface_hub,
        "try_to_load_from_cache",
        return_value=Path("/fake/cache/config.json"),
    )
    assert transcribe_mod.is_model_cached(MODEL) is True


def test_is_model_cached_returns_false_when_not_cached(mocker) -> None:
    mocker.patch.object(
        transcribe_mod.huggingface_hub,
        "try_to_load_from_cache",
        return_value=None,
    )
    assert transcribe_mod.is_model_cached(MODEL) is False


def test_download_model_calls_snapshot_download(mocker) -> None:
    spy = mocker.patch.object(
        transcribe_mod.huggingface_hub, "snapshot_download", return_value="/fake/path"
    )
    transcribe_mod.download_model(MODEL)
    spy.assert_called_once_with(repo_id=MODEL)


def test_download_model_wraps_errors_as_model_download_error(mocker) -> None:
    mocker.patch.object(
        transcribe_mod.huggingface_hub,
        "snapshot_download",
        side_effect=RuntimeError("network down"),
    )
    with pytest.raises(ModelDownloadError, match="network down"):
        transcribe_mod.download_model(MODEL)


def test_warmup_calls_transcribe_with_silent_audio(mocker) -> None:
    spy = mocker.patch.object(
        transcribe_mod.mlx_whisper,
        "transcribe",
        return_value={"text": "", "segments": [], "language": "en"},
    )
    transcribe_mod.warmup(MODEL, LANG)
    spy.assert_called_once()
    args, kwargs = spy.call_args
    audio = args[0]
    assert isinstance(audio, np.ndarray)
    assert audio.shape == (1600,)
    assert audio.dtype == np.float32
    assert np.all(audio == 0.0)
    assert kwargs["path_or_hf_repo"] == MODEL
    assert kwargs["language"] == LANG


def test_warmup_wraps_errors_as_model_load_error(mocker) -> None:
    mocker.patch.object(
        transcribe_mod.mlx_whisper,
        "transcribe",
        side_effect=RuntimeError("mlx boom"),
    )
    with pytest.raises(ModelLoadError, match="mlx boom"):
        transcribe_mod.warmup(MODEL, LANG)


def test_transcribe_returns_text_from_result(mocker) -> None:
    mocker.patch.object(
        transcribe_mod.mlx_whisper,
        "transcribe",
        return_value={"text": "hello world", "segments": [], "language": "en"},
    )
    audio = np.zeros(16000, dtype=np.int16)
    assert transcribe_mod.transcribe(audio, MODEL, LANG) == "hello world"


def test_transcribe_strips_leading_and_trailing_whitespace(mocker) -> None:
    mocker.patch.object(
        transcribe_mod.mlx_whisper,
        "transcribe",
        return_value={"text": "  hello world  ", "segments": [], "language": "en"},
    )
    audio = np.zeros(16000, dtype=np.int16)
    assert transcribe_mod.transcribe(audio, MODEL, LANG) == "hello world"


def test_transcribe_converts_int16_to_float32_at_boundary(mocker) -> None:
    spy = mocker.patch.object(
        transcribe_mod.mlx_whisper,
        "transcribe",
        return_value={"text": "", "segments": [], "language": "en"},
    )
    audio = np.array([0, 16384, -16384, 32767], dtype=np.int16)
    transcribe_mod.transcribe(audio, MODEL, LANG)
    args, _ = spy.call_args
    passed = args[0]
    assert passed.dtype == np.float32
    assert passed.shape == audio.shape
    assert abs(passed[1] - (16384.0 / 32768.0)) < 1e-6


def test_transcribe_wraps_errors_as_transcribe_error(mocker) -> None:
    mocker.patch.object(
        transcribe_mod.mlx_whisper,
        "transcribe",
        side_effect=RuntimeError("decode failed"),
    )
    audio = np.zeros(1600, dtype=np.int16)
    with pytest.raises(TranscribeError, match="decode failed"):
        transcribe_mod.transcribe(audio, MODEL, LANG)


def test_transcribe_passes_language_kwarg(mocker) -> None:
    spy = mocker.patch.object(
        transcribe_mod.mlx_whisper,
        "transcribe",
        return_value={"text": "bonjour", "segments": [], "language": "fr"},
    )
    audio = np.zeros(1600, dtype=np.int16)
    transcribe_mod.transcribe(audio, MODEL, "fr")
    _, kwargs = spy.call_args
    assert kwargs["language"] == "fr"
    assert kwargs["path_or_hf_repo"] == MODEL


def test_transcribe_rejects_non_int16_audio(mocker) -> None:
    mocker.patch.object(
        transcribe_mod.mlx_whisper,
        "transcribe",
        return_value={"text": "", "segments": [], "language": "en"},
    )
    audio = np.zeros(1600, dtype=np.float32)
    with pytest.raises(TypeError):
        transcribe_mod.transcribe(audio, MODEL, LANG)
