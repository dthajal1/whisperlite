from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

import tomli as tomllib

from whisperlite.errors import ConfigError

logger = logging.getLogger(__name__)

PROJECT_CONFIG_FILENAME = "whisperlite.toml"
USER_CONFIG_PATH = Path("~/.config/whisperlite/config.toml").expanduser()
DEFAULT_CONFIG_PATH = USER_CONFIG_PATH
CONFIG_ENV_VAR = "WHISPERLITE_CONFIG"

_VALID_SAMPLE_RATES = {8000, 16000, 22050, 44100, 48000}
_VALID_CHANNELS = {1, 2}
_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_KNOWN_TABLES = {"model", "hotkey", "audio", "inject", "ui", "log", "sound"}

_BUNDLED_ASSETS_DIR = Path(__file__).parent / "assets"
_DEFAULT_IDLE_ICON = _BUNDLED_ASSETS_DIR / "idle.png"
_DEFAULT_RECORDING_ICON = _BUNDLED_ASSETS_DIR / "recording.png"
_DEFAULT_ERROR_ICON = _BUNDLED_ASSETS_DIR / "error.png"

_DEFAULT_START_SOUND = Path("/System/Library/Sounds/Tink.aiff")
_DEFAULT_STOP_SOUND = Path("/System/Library/Sounds/Pop.aiff")


@dataclass(frozen=True)
class ModelConfig:
    """Whisper model selection and language."""

    name: str = "mlx-community/whisper-medium-mlx"
    language: str = "en"


_VALID_HOTKEY_MODIFIERS = {"<alt>", "<shift>", "<ctrl>", "<cmd>"}


@dataclass(frozen=True)
class HotkeyConfig:
    """Double-tap modifier to trigger record."""

    record: str = "<alt>"
    double_tap_window_ms: int = 400


@dataclass(frozen=True)
class AudioConfig:
    """Mic capture parameters and recording cap."""

    max_recording_seconds: int = 60
    sample_rate: int = 16000
    channels: int = 1


@dataclass(frozen=True)
class InjectConfig:
    """Text injection timing."""

    paste_delay_ms: int = 150


@dataclass(frozen=True)
class UIConfig:
    """Menubar icons for the three steady-state states."""

    idle_icon: Path = field(default_factory=lambda: _DEFAULT_IDLE_ICON)
    recording_icon: Path = field(default_factory=lambda: _DEFAULT_RECORDING_ICON)
    error_icon: Path = field(default_factory=lambda: _DEFAULT_ERROR_ICON)


@dataclass(frozen=True)
class LogConfig:
    """Log level and rotating file path."""

    level: str = "INFO"
    path: str = "~/Library/Logs/whisperlite.log"


@dataclass(frozen=True)
class SoundConfig:
    """Short audio cues played on recording start/stop."""

    enabled: bool = True
    start_path: Path = field(default_factory=lambda: _DEFAULT_START_SOUND)
    stop_path: Path = field(default_factory=lambda: _DEFAULT_STOP_SOUND)


@dataclass(frozen=True)
class Config:
    """Top-level whisperlite config, one field per TOML table."""

    model: ModelConfig = field(default_factory=ModelConfig)
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    inject: InjectConfig = field(default_factory=InjectConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    log: LogConfig = field(default_factory=LogConfig)
    sound: SoundConfig = field(default_factory=SoundConfig)


def get_effective_config_path() -> Path:
    """Return the path ``load_config()`` would use right now.

    Priority:
      1. ``$WHISPERLITE_CONFIG`` (expanded), if set.
      2. ``Path.cwd() / PROJECT_CONFIG_FILENAME`` if it exists.
      3. ``USER_CONFIG_PATH`` if it exists.
      4. Fallback: ``Path.cwd() / PROJECT_CONFIG_FILENAME`` as the
         "would be created here" default (write destination).

    This function does NOT check whether the returned path exists — it
    only returns a path. Callers decide what to do if the file is
    missing (e.g. ``ensure_config_exists``).
    """
    env_value = os.environ.get(CONFIG_ENV_VAR, "").strip()
    if env_value:
        return Path(env_value).expanduser()

    project_candidate = Path.cwd() / PROJECT_CONFIG_FILENAME
    if project_candidate.exists():
        return project_candidate

    if USER_CONFIG_PATH.exists():
        return USER_CONFIG_PATH

    return project_candidate


_MINIMAL_STUB = """\
# whisperlite config — auto-generated stub.

[model]
name = "mlx-community/whisper-medium-mlx"
language = "en"
"""


def ensure_config_exists(path: Path) -> None:
    """Create ``path`` from the bundled example config if it doesn't exist.

    Falls back to a minimal ``[model]`` stub if ``config.example.toml``
    cannot be located. No-op if the file already exists.
    """
    if path.exists():
        return

    example = Path(__file__).parent.parent / "config.example.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    if example.exists():
        shutil.copyfile(example, path)
    else:
        path.write_text(_MINIMAL_STUB)
    logger.info("created new config file at %s", path)


def _find_config_path() -> Path | None:
    """Return the first existing config path in priority order, or None."""
    env_value = os.environ.get(CONFIG_ENV_VAR, "").strip()
    if env_value:
        candidate = Path(env_value).expanduser()
        if candidate.exists():
            return candidate

    project_candidate = Path.cwd() / PROJECT_CONFIG_FILENAME
    if project_candidate.exists():
        return project_candidate

    if USER_CONFIG_PATH.exists():
        return USER_CONFIG_PATH

    return None


def load_config(path: Path | None = None) -> Config:
    """Load and validate a whisperlite TOML config, falling back to defaults."""
    if path is not None:
        target: Path | None = path
    else:
        target = _find_config_path()

    if target is None or not target.exists():
        if target is not None:
            logger.debug("config file %s not found, using defaults", target)
        else:
            logger.debug("no whisperlite config found, using defaults")
        config = _normalize(Config())
        _validate(config)
        return config

    try:
        raw = tomllib.loads(target.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"failed to parse TOML at {target}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"failed to read config at {target}: {exc}") from exc

    for key in raw:
        if key not in _KNOWN_TABLES:
            logger.warning("unknown top-level config key %r (ignored)", key)

    config = _normalize(_overlay(raw))
    _validate(config)
    logger.info("loaded config from %s", target)
    return config


def _normalize(config: Config) -> Config:
    log = config.log
    level = log.level.upper() if isinstance(log.level, str) else log.level
    path_str = (
        str(Path(log.path).expanduser()) if isinstance(log.path, str) else log.path
    )
    return replace(config, log=replace(log, level=level, path=path_str))


def _overlay(raw: dict[str, Any]) -> Config:
    defaults = Config()
    try:
        model = _overlay_dataclass(defaults.model, raw.get("model", {}))
        hotkey = _overlay_dataclass(defaults.hotkey, raw.get("hotkey", {}))
        audio = _overlay_dataclass(defaults.audio, raw.get("audio", {}))
        inject = _overlay_dataclass(defaults.inject, raw.get("inject", {}))
        ui = _overlay_ui(defaults.ui, raw.get("ui", {}))
        log = _overlay_dataclass(defaults.log, raw.get("log", {}))
        sound = _overlay_sound(defaults.sound, raw.get("sound", {}))
    except TypeError as exc:
        raise ConfigError(f"config table has the wrong shape: {exc}") from exc

    return Config(
        model=model,
        hotkey=hotkey,
        audio=audio,
        inject=inject,
        ui=ui,
        log=log,
        sound=sound,
    )


_SOUND_PATH_FIELDS = ("start_path", "stop_path")


def _overlay_sound(default: SoundConfig, table: Any) -> SoundConfig:
    if not isinstance(table, dict):
        raise ConfigError(
            f"[sound] expected table, got {type(table).__name__}"
        )
    updates: dict[str, Any] = {}
    known = {f.name for f in fields(default)}
    for key, value in table.items():
        if key not in known:
            logger.warning("unknown config key %r under [sound] (ignored)", key)
            continue
        if key in _SOUND_PATH_FIELDS:
            if not isinstance(value, str) or not value:
                raise ConfigError(
                    f"[sound] {key} must be a non-empty string, got {value!r}"
                )
            updates[key] = Path(value).expanduser()
        else:
            updates[key] = value
    return replace(default, **updates)


_UI_ICON_FIELDS = ("idle_icon", "recording_icon", "error_icon")


def _resolve_icon_path(value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise ConfigError(
            f"[ui] icon paths must be non-empty strings, got {value!r}"
        )
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return candidate
    cwd_candidate = (Path.cwd() / candidate).resolve()
    if cwd_candidate.exists():
        return cwd_candidate
    bundled_candidate = (_BUNDLED_ASSETS_DIR / candidate).resolve()
    if bundled_candidate.exists():
        return bundled_candidate
    return cwd_candidate


def _overlay_ui(default: UIConfig, table: Any) -> UIConfig:
    if not isinstance(table, dict):
        raise ConfigError(
            f"[ui] expected table, got {type(table).__name__}"
        )
    updates: dict[str, Any] = {}
    known = {f.name for f in fields(default)}
    for key, value in table.items():
        if key not in known:
            logger.warning("unknown config key %r under [ui] (ignored)", key)
            continue
        if key in _UI_ICON_FIELDS:
            updates[key] = _resolve_icon_path(value)
        else:
            updates[key] = value
    return replace(default, **updates)


def _overlay_dataclass(default: Any, table: Any) -> Any:
    if not isinstance(table, dict):
        raise TypeError(f"expected table, got {type(table).__name__}")
    known = {f.name for f in fields(default)}
    updates: dict[str, Any] = {}
    for key, value in table.items():
        if key not in known:
            logger.warning(
                "unknown config key %r under [%s] (ignored)",
                key,
                type(default).__name__,
            )
            continue
        updates[key] = value
    return replace(default, **updates)


def _validate(config: Config) -> None:
    _validate_model(config.model)
    _validate_audio(config.audio)
    _validate_inject(config.inject)
    _validate_ui(config.ui)
    _validate_log_shape(config.log)
    _validate_hotkey(config.hotkey)
    _validate_sound(config.sound)


def _validate_model(model: ModelConfig) -> None:
    if not isinstance(model.name, str) or not model.name:
        raise ConfigError("[model] name must be a non-empty string")
    parts = model.name.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ConfigError(
            f"[model] name must be of the form '<org>/<name>', got {model.name!r}"
        )
    if not isinstance(model.language, str) or not model.language:
        raise ConfigError("[model] language must be a non-empty string")


def _validate_audio(audio: AudioConfig) -> None:
    if not _is_plain_int(audio.max_recording_seconds):
        raise ConfigError(
            "[audio] max_recording_seconds must be an integer, got "
            f"{audio.max_recording_seconds!r} ({type(audio.max_recording_seconds).__name__})"
        )
    if not 5 <= audio.max_recording_seconds <= 600:
        raise ConfigError(
            "[audio] max_recording_seconds must be in [5, 600], got "
            f"{audio.max_recording_seconds}"
        )
    if not _is_plain_int(audio.sample_rate):
        raise ConfigError(
            f"[audio] sample_rate must be an integer, got {audio.sample_rate!r}"
        )
    if audio.sample_rate not in _VALID_SAMPLE_RATES:
        raise ConfigError(
            f"[audio] sample_rate must be one of {sorted(_VALID_SAMPLE_RATES)}, "
            f"got {audio.sample_rate}"
        )
    if not _is_plain_int(audio.channels):
        raise ConfigError(
            f"[audio] channels must be an integer, got {audio.channels!r}"
        )
    if audio.channels not in _VALID_CHANNELS:
        raise ConfigError(
            f"[audio] channels must be one of {sorted(_VALID_CHANNELS)}, "
            f"got {audio.channels}"
        )


def _validate_inject(inject: InjectConfig) -> None:
    if not _is_plain_int(inject.paste_delay_ms):
        raise ConfigError(
            f"[inject] paste_delay_ms must be an integer, got {inject.paste_delay_ms!r}"
        )
    if not 0 <= inject.paste_delay_ms <= 2000:
        raise ConfigError(
            f"[inject] paste_delay_ms must be in [0, 2000], got {inject.paste_delay_ms}"
        )


def _validate_ui(ui: UIConfig) -> None:
    for name in _UI_ICON_FIELDS:
        value = getattr(ui, name)
        if not isinstance(value, Path):
            raise ConfigError(
                f"[ui] {name} must be a Path, got {type(value).__name__}"
            )
        if not value.exists():
            raise ConfigError(
                f"[ui] {name} path does not exist: {value}"
            )


def _validate_log_shape(log: LogConfig) -> None:
    if not isinstance(log.level, str):
        raise ConfigError(f"[log] level must be a string, got {log.level!r}")
    normalized = log.level.upper()
    if normalized not in _VALID_LOG_LEVELS:
        raise ConfigError(
            f"[log] level must be one of {sorted(_VALID_LOG_LEVELS)}, got {log.level!r}"
        )
    if not isinstance(log.path, str) or not log.path:
        raise ConfigError("[log] path must be a non-empty string")


def _validate_hotkey(hotkey: HotkeyConfig) -> None:
    if not isinstance(hotkey.record, str) or not hotkey.record:
        raise ConfigError("[hotkey] record must be a non-empty string")
    if hotkey.record not in _VALID_HOTKEY_MODIFIERS:
        raise ConfigError(
            "[hotkey] record must be one of "
            f"{sorted(_VALID_HOTKEY_MODIFIERS)}, got {hotkey.record!r}"
        )
    if not _is_plain_int(hotkey.double_tap_window_ms):
        raise ConfigError(
            "[hotkey] double_tap_window_ms must be an integer, got "
            f"{hotkey.double_tap_window_ms!r}"
        )
    if not 150 <= hotkey.double_tap_window_ms <= 1000:
        raise ConfigError(
            "[hotkey] double_tap_window_ms must be in [150, 1000], got "
            f"{hotkey.double_tap_window_ms}"
        )


def _validate_sound(sound: SoundConfig) -> None:
    if not isinstance(sound.enabled, bool):
        raise ConfigError(
            f"[sound] enabled must be a bool, got {sound.enabled!r} "
            f"({type(sound.enabled).__name__})"
        )
    for name in _SOUND_PATH_FIELDS:
        value = getattr(sound, name)
        if not isinstance(value, Path):
            raise ConfigError(
                f"[sound] {name} must be a Path, got {type(value).__name__}"
            )
        if not value.exists():
            raise ConfigError(
                f"[sound] {name} does not exist: {value}"
            )


def _is_plain_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
