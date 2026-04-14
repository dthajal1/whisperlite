from __future__ import annotations

import pytest

from whisperlite.errors import (
    AudioDeviceError,
    AudioStreamError,
    ConfigError,
    InjectError,
    ModelDownloadError,
    ModelLoadError,
    TranscribeError,
    WhisperliteError,
    WhisperlitePermissionError,
)

_SUBCLASSES = [
    WhisperlitePermissionError,
    AudioDeviceError,
    AudioStreamError,
    ModelLoadError,
    ModelDownloadError,
    TranscribeError,
    InjectError,
    ConfigError,
]


def test_base_inherits_exception() -> None:
    assert issubclass(WhisperliteError, Exception)


@pytest.mark.parametrize("cls", _SUBCLASSES)
def test_subclasses_inherit_base(cls: type[WhisperliteError]) -> None:
    assert issubclass(cls, WhisperliteError)


@pytest.mark.parametrize("cls", _SUBCLASSES)
def test_subclasses_preserve_message(cls: type[WhisperliteError]) -> None:
    err = cls("boom")
    assert str(err) == "boom"
    assert isinstance(err, WhisperliteError)


def test_permission_error_does_not_shadow_builtin() -> None:
    assert WhisperlitePermissionError is not PermissionError
    assert not issubclass(WhisperlitePermissionError, PermissionError)
