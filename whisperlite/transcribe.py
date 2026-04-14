from __future__ import annotations

import logging
import time

import huggingface_hub
import mlx_whisper
import numpy as np

from whisperlite.errors import ModelDownloadError, ModelLoadError, TranscribeError

logger = logging.getLogger(__name__)

_WARMUP_SAMPLES = 1600  # 0.1s of silence at 16kHz
_INT16_MAX = 32768.0


def _int16_to_float32(arr: np.ndarray) -> np.ndarray:
    """Convert an int16 PCM numpy array to float32 in [-1, 1]."""
    if not isinstance(arr, np.ndarray):
        raise TypeError(f"expected numpy.ndarray, got {type(arr).__name__}")
    if arr.dtype != np.int16:
        raise TypeError(f"expected int16 array, got dtype {arr.dtype}")
    return arr.astype(np.float32) / _INT16_MAX


def is_model_cached(model_name: str) -> bool:
    """Return True if the Whisper model is already present in the HF cache."""
    path = huggingface_hub.try_to_load_from_cache(
        repo_id=model_name, filename="config.json"
    )
    return path is not None


def download_model(model_name: str) -> None:
    """Blocking download of a Whisper model from Hugging Face."""
    logger.info("downloading model %s", model_name)
    try:
        huggingface_hub.snapshot_download(repo_id=model_name)
    except Exception as exc:
        raise ModelDownloadError(
            f"failed to download {model_name}: {exc}"
        ) from exc
    logger.info("finished downloading model %s", model_name)


def warmup(model_name: str, language: str) -> None:
    """Prime the mlx-whisper model cache with a short silent clip."""
    silent = np.zeros(_WARMUP_SAMPLES, dtype=np.float32)
    start = time.monotonic()
    try:
        mlx_whisper.transcribe(
            silent,
            path_or_hf_repo=model_name,
            language=language,
        )
    except Exception as exc:
        raise ModelLoadError(
            f"failed to warm up {model_name}: {exc}"
        ) from exc
    duration_ms = (time.monotonic() - start) * 1000.0
    logger.info("warmed up model %s in %.0fms", model_name, duration_ms)


def transcribe(
    audio_int16: np.ndarray, model_name: str, language: str
) -> str:
    """Transcribe a mono int16 16kHz numpy array into text."""
    audio_float32 = _int16_to_float32(audio_int16)
    audio_seconds = audio_float32.shape[-1] / 16000.0
    start = time.monotonic()
    try:
        result = mlx_whisper.transcribe(
            audio_float32,
            path_or_hf_repo=model_name,
            language=language,
        )
    except Exception as exc:
        raise TranscribeError(
            f"mlx-whisper transcription failed: {exc}"
        ) from exc
    duration_ms = (time.monotonic() - start) * 1000.0
    logger.debug(
        "transcribed %.2fs of audio in %.0fms", audio_seconds, duration_ms
    )
    return result["text"].strip()
