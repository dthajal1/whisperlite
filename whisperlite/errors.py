from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class WhisperliteError(Exception):
    """Base class for all whisperlite errors; never raised directly."""


class WhisperlitePermissionError(WhisperliteError):
    """Raised when a required macOS TCC permission is missing."""


class AudioDeviceError(WhisperliteError):
    """Raised when the audio input device cannot be opened or is missing."""


class AudioStreamError(WhisperliteError):
    """Raised when an active audio stream fails mid-capture."""


class ModelLoadError(WhisperliteError):
    """Raised when the Whisper model fails to load into memory."""


class ModelDownloadError(WhisperliteError):
    """Raised when the Whisper model fails to download from Hugging Face."""


class TranscribeError(WhisperliteError):
    """Raised when transcription fails inside mlx-whisper."""


class InjectError(WhisperliteError):
    """Raised when text injection into the target app fails."""


class ConfigError(WhisperliteError):
    """Raised when the TOML config cannot be parsed or fails validation."""
