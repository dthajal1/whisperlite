from __future__ import annotations

import subprocess
from pathlib import Path

from whisperlite import sounds as sounds_mod
from whisperlite.sounds import DEFAULT_START_SOUND, DEFAULT_STOP_SOUND, play


def test_play_invokes_afplay_with_correct_path(mocker) -> None:
    popen_mock = mocker.patch.object(sounds_mod.subprocess, "Popen")
    play(Path("/tmp/x.aiff"))
    assert popen_mock.call_count == 1
    args, kwargs = popen_mock.call_args
    assert args[0] == ["afplay", "/tmp/x.aiff"]
    assert kwargs["stdout"] == subprocess.DEVNULL
    assert kwargs["stderr"] == subprocess.DEVNULL


def test_play_returns_immediately_without_waiting(mocker) -> None:
    fake_proc = mocker.MagicMock(name="popen_instance")
    mocker.patch.object(sounds_mod.subprocess, "Popen", return_value=fake_proc)
    play(Path("/tmp/x.aiff"))
    fake_proc.wait.assert_not_called()
    fake_proc.communicate.assert_not_called()


def test_play_swallows_exceptions(mocker, caplog) -> None:
    mocker.patch.object(
        sounds_mod.subprocess,
        "Popen",
        side_effect=FileNotFoundError("afplay not found"),
    )
    with caplog.at_level("DEBUG", logger="whisperlite.sounds"):
        play(Path("/tmp/x.aiff"))  # must not raise
    assert any("failed to play sound" in r.message for r in caplog.records)


def test_play_swallows_oserror(mocker) -> None:
    mocker.patch.object(
        sounds_mod.subprocess, "Popen", side_effect=OSError("boom")
    )
    play(Path("/tmp/x.aiff"))  # must not raise


def test_default_start_sound_path_points_to_system_file() -> None:
    assert DEFAULT_START_SOUND == Path("/System/Library/Sounds/Tink.aiff")


def test_default_stop_sound_path_points_to_system_file() -> None:
    assert DEFAULT_STOP_SOUND == Path("/System/Library/Sounds/Pop.aiff")
