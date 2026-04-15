from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# macOS built-in system sounds
DEFAULT_START_SOUND = Path("/System/Library/Sounds/Bottle.aiff")
DEFAULT_STOP_SOUND = Path("/System/Library/Sounds/Glass.aiff")


def play(sound_path: Path) -> None:
    """Play a sound file asynchronously using macOS afplay."""
    try:
        subprocess.Popen(
            ["afplay", str(sound_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        logger.debug("failed to play sound %s: %s", sound_path, exc)
