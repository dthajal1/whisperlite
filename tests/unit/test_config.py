from __future__ import annotations

import logging
from pathlib import Path

import pytest

from whisperlite import config as config_module
from whisperlite.config import (
    AudioConfig,
    Config,
    HotkeyConfig,
    InjectConfig,
    LogConfig,
    ModelConfig,
    SoundConfig,
    UIConfig,
    _BUNDLED_ASSETS_DIR,
    _DEFAULT_ERROR_ICON,
    _DEFAULT_IDLE_ICON,
    _DEFAULT_RECORDING_ICON,
    _DEFAULT_START_SOUND,
    _DEFAULT_STOP_SOUND,
    _find_config_path,
    ensure_config_exists,
    get_effective_config_path,
    load_config,
)
from whisperlite.errors import ConfigError


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(body)
    return p


def test_default_config_when_file_missing(tmp_path: Path) -> None:
    missing = tmp_path / "nope.toml"
    config = load_config(missing)
    assert isinstance(config, Config)
    assert config.model.name == "mlx-community/whisper-small-mlx"


def test_default_config_values(tmp_path: Path) -> None:
    config = load_config(tmp_path / "nope.toml")
    assert config.model == ModelConfig(
        name="mlx-community/whisper-small-mlx", language="en"
    )
    assert config.hotkey == HotkeyConfig(record="<alt>", double_tap_window_ms=400)
    assert config.audio == AudioConfig(
        max_recording_seconds=60, sample_rate=16000, channels=1
    )
    assert config.inject == InjectConfig(paste_delay_ms=150)
    assert config.ui == UIConfig()
    assert config.log.level == "INFO"
    assert config.log.path == str(Path("~/Library/Logs/whisperlite.log").expanduser())


def test_load_config_with_user_overlay(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        [audio]
        max_recording_seconds = 30
        """,
    )
    config = load_config(path)
    assert config.audio.max_recording_seconds == 30
    assert config.audio.sample_rate == 16000
    assert config.model.name == "mlx-community/whisper-small-mlx"


def test_load_config_partial_table(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        [model]
        name = "org/custom-model"
        """,
    )
    config = load_config(path)
    assert config.model.name == "org/custom-model"
    assert config.model.language == "en"
    assert config.hotkey.record == "<alt>"


def test_invalid_toml_raises_config_error(tmp_path: Path) -> None:
    path = _write(tmp_path, "this = = not toml")
    with pytest.raises(ConfigError):
        load_config(path)


def test_validation_max_recording_seconds_too_low(tmp_path: Path) -> None:
    path = _write(tmp_path, "[audio]\nmax_recording_seconds = 1\n")
    with pytest.raises(ConfigError, match="max_recording_seconds"):
        load_config(path)


def test_validation_max_recording_seconds_too_high(tmp_path: Path) -> None:
    path = _write(tmp_path, "[audio]\nmax_recording_seconds = 9999\n")
    with pytest.raises(ConfigError, match="max_recording_seconds"):
        load_config(path)


def test_validation_max_recording_seconds_wrong_type(tmp_path: Path) -> None:
    path = _write(tmp_path, '[audio]\nmax_recording_seconds = "sixty"\n')
    with pytest.raises(ConfigError, match="max_recording_seconds"):
        load_config(path)


def test_validation_sample_rate_invalid(tmp_path: Path) -> None:
    path = _write(tmp_path, "[audio]\nsample_rate = 12345\n")
    with pytest.raises(ConfigError, match="sample_rate"):
        load_config(path)


def test_validation_paste_delay_negative(tmp_path: Path) -> None:
    path = _write(tmp_path, "[inject]\npaste_delay_ms = -1\n")
    with pytest.raises(ConfigError, match="paste_delay_ms"):
        load_config(path)


def test_validation_log_level_invalid(tmp_path: Path) -> None:
    path = _write(tmp_path, '[log]\nlevel = "TRACE"\n')
    with pytest.raises(ConfigError, match="level"):
        load_config(path)


def test_validation_log_level_case_insensitive(tmp_path: Path) -> None:
    path = _write(tmp_path, '[log]\nlevel = "info"\n')
    config = load_config(path)
    assert config.log.level == "INFO"


def test_validation_model_name_format(tmp_path: Path) -> None:
    path = _write(tmp_path, '[model]\nname = "noslash"\n')
    with pytest.raises(ConfigError, match="name"):
        load_config(path)


def test_validation_hotkey_invalid_keyspec(tmp_path: Path) -> None:
    path = _write(tmp_path, '[hotkey]\nrecord = "<<<>>>"\n')
    with pytest.raises(ConfigError, match="record"):
        load_config(path)


def test_unknown_top_level_key_logs_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = _write(
        tmp_path,
        """
        [unknown_table]
        foo = "bar"
        """,
    )
    with caplog.at_level(logging.WARNING, logger="whisperlite.config"):
        config = load_config(path)
    assert any("unknown_table" in rec.message for rec in caplog.records)
    assert config.model.name == "mlx-community/whisper-small-mlx"


def test_path_field_expands_tilde(tmp_path: Path) -> None:
    path = _write(tmp_path, '[log]\npath = "~/whisperlite-test.log"\n')
    config = load_config(path)
    assert not config.log.path.startswith("~")
    assert config.log.path == str(Path("~/whisperlite-test.log").expanduser())


def test_find_config_path_uses_env_var_when_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_path = tmp_path / "from-env.toml"
    env_path.write_text("[model]\nname = \"org/env-model\"\n")
    monkeypatch.setenv("WHISPERLITE_CONFIG", str(env_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config_module, "USER_CONFIG_PATH", tmp_path / "nouser.toml")
    assert _find_config_path() == env_path


def test_find_config_path_prefers_project_over_user_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    project_cfg = project_dir / "whisperlite.toml"
    project_cfg.write_text("[model]\nname = \"org/project-model\"\n")
    user_cfg = tmp_path / "user.toml"
    user_cfg.write_text("[model]\nname = \"org/user-model\"\n")
    monkeypatch.delenv("WHISPERLITE_CONFIG", raising=False)
    monkeypatch.chdir(project_dir)
    monkeypatch.setattr(config_module, "USER_CONFIG_PATH", user_cfg)
    assert _find_config_path() == project_cfg


def test_find_config_path_falls_back_to_user_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    user_cfg = tmp_path / "user.toml"
    user_cfg.write_text("[model]\nname = \"org/user-model\"\n")
    monkeypatch.delenv("WHISPERLITE_CONFIG", raising=False)
    monkeypatch.chdir(empty_dir)
    monkeypatch.setattr(config_module, "USER_CONFIG_PATH", user_cfg)
    assert _find_config_path() == user_cfg


def test_find_config_path_returns_none_when_nothing_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    monkeypatch.delenv("WHISPERLITE_CONFIG", raising=False)
    monkeypatch.chdir(empty_dir)
    monkeypatch.setattr(config_module, "USER_CONFIG_PATH", tmp_path / "nouser.toml")
    assert _find_config_path() is None


def test_get_effective_config_path_returns_env_var_when_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_path = tmp_path / "does-not-exist.toml"
    monkeypatch.setenv("WHISPERLITE_CONFIG", str(env_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config_module, "USER_CONFIG_PATH", tmp_path / "nouser.toml")
    assert get_effective_config_path() == env_path


def test_get_effective_config_path_returns_project_local_when_it_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("WHISPERLITE_CONFIG", raising=False)
    project_cfg = tmp_path / "whisperlite.toml"
    project_cfg.write_text("[model]\nname = \"org/proj\"\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config_module, "USER_CONFIG_PATH", tmp_path / "nouser.toml")
    assert get_effective_config_path() == project_cfg


def test_get_effective_config_path_returns_user_config_when_project_local_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    user_cfg = tmp_path / "user.toml"
    user_cfg.write_text("[model]\nname = \"org/user\"\n")
    monkeypatch.delenv("WHISPERLITE_CONFIG", raising=False)
    monkeypatch.chdir(empty_dir)
    monkeypatch.setattr(config_module, "USER_CONFIG_PATH", user_cfg)
    assert get_effective_config_path() == user_cfg


def test_get_effective_config_path_returns_project_local_as_default_when_nothing_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    monkeypatch.delenv("WHISPERLITE_CONFIG", raising=False)
    monkeypatch.chdir(empty_dir)
    monkeypatch.setattr(config_module, "USER_CONFIG_PATH", tmp_path / "nouser.toml")
    result = get_effective_config_path()
    assert result == empty_dir / "whisperlite.toml"
    assert not result.exists()


def test_ensure_config_exists_creates_from_example(tmp_path: Path) -> None:
    target = tmp_path / "new.toml"
    assert not target.exists()
    ensure_config_exists(target)
    assert target.exists()
    assert "[model]" in target.read_text()


def test_ensure_config_exists_is_noop_when_file_exists(tmp_path: Path) -> None:
    target = tmp_path / "existing.toml"
    marker = "# sentinel content — do not overwrite\n[model]\nname = \"org/x\"\n"
    target.write_text(marker)
    ensure_config_exists(target)
    assert target.read_text() == marker


def test_default_ui_config_uses_bundled_assets() -> None:
    ui = UIConfig()
    assert ui.idle_icon == _DEFAULT_IDLE_ICON
    assert ui.recording_icon == _DEFAULT_RECORDING_ICON
    assert ui.error_icon == _DEFAULT_ERROR_ICON
    assert ui.idle_icon.parent == _BUNDLED_ASSETS_DIR
    assert ui.idle_icon.exists()
    assert ui.recording_icon.exists()
    assert ui.error_icon.exists()


def test_validation_icon_path_does_not_exist(tmp_path: Path) -> None:
    missing = tmp_path / "nope.png"
    body = f'[ui]\nidle_icon = "{missing}"\n'
    path = _write(tmp_path, body)
    with pytest.raises(ConfigError, match="idle_icon"):
        load_config(path)


def test_default_sound_config_is_enabled(tmp_path: Path) -> None:
    config = load_config(tmp_path / "nope.toml")
    assert config.sound.enabled is True


def test_default_sound_paths_point_to_system_sounds(tmp_path: Path) -> None:
    config = load_config(tmp_path / "nope.toml")
    assert config.sound.start_path == _DEFAULT_START_SOUND
    assert config.sound.stop_path == _DEFAULT_STOP_SOUND


def test_sound_enabled_false_disables_sounds(tmp_path: Path) -> None:
    path = _write(tmp_path, "[sound]\nenabled = false\n")
    config = load_config(path)
    assert config.sound.enabled is False


def test_custom_start_path_is_loaded(tmp_path: Path) -> None:
    fake_sound = tmp_path / "custom.aiff"
    fake_sound.write_bytes(b"\x00\x01")
    body = f'[sound]\nstart_path = "{fake_sound}"\n'
    path = _write(tmp_path, body)
    config = load_config(path)
    assert config.sound.start_path == fake_sound


def test_sound_validation_nonexistent_path_raises_config_error(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path, '[sound]\nstart_path = "/tmp/whisperlite-nope-xyz.aiff"\n')
    with pytest.raises(ConfigError, match="start_path"):
        load_config(path)


def test_sound_enabled_wrong_type_raises_config_error(tmp_path: Path) -> None:
    path = _write(tmp_path, '[sound]\nenabled = "yes"\n')
    with pytest.raises(ConfigError, match="enabled"):
        load_config(path)


def test_load_config_with_no_files_returns_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    monkeypatch.delenv("WHISPERLITE_CONFIG", raising=False)
    monkeypatch.chdir(empty_dir)
    monkeypatch.setattr(config_module, "USER_CONFIG_PATH", tmp_path / "nouser.toml")
    config = load_config()
    assert isinstance(config, Config)
    assert config.model == ModelConfig()
    assert config.hotkey == HotkeyConfig()
    assert config.audio == AudioConfig()
    assert config.hotkey.record == "<alt>"
