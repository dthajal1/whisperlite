from __future__ import annotations

import logging
import signal
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import FrameType

import rumps

from whisperlite.app import WhisperliteApp
from whisperlite.config import load_config
from whisperlite.errors import ConfigError, WhisperliteError

logger = logging.getLogger(__name__)

_POST_LAUNCH_DELAY_S = 0.1


def _setup_logging(level: str, path: str) -> None:
    """Configure the root logger with a rotating file handler."""
    log_path = Path(path).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=3)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


def _install_signal_handlers(app: WhisperliteApp) -> None:
    """Install SIGINT and SIGTERM handlers that trigger a clean shutdown."""

    def handler(signum: int, _frame: FrameType | None) -> None:
        logger.info("received signal %s, shutting down", signum)
        try:
            app.shutdown()
        finally:
            rumps.quit_application()

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)


def _schedule_post_launch_init(app: WhisperliteApp) -> None:
    """Schedule a one-shot rumps.Timer to run TCC-sensitive init on main thread."""
    fired = {"done": False}
    timer_ref: dict[str, rumps.Timer] = {}

    def _fire(sender: rumps.Timer) -> None:
        if fired["done"]:
            return
        fired["done"] = True
        try:
            sender.stop()
        except Exception:
            pass
        try:
            app.post_launch_init()
        except Exception:
            logger.exception("post_launch_init failed")

    timer = rumps.Timer(_fire, _POST_LAUNCH_DELAY_S)
    timer_ref["t"] = timer
    timer.start()


def main() -> int:
    """Load config, set up logging, start the menubar app, and run the event loop."""
    try:
        config = load_config()
    except ConfigError as exc:
        sys.stderr.write(f"whisperlite: config error: {exc}\n")
        return 1

    _setup_logging(config.log.level, config.log.path)
    logger.info("whisperlite starting")

    try:
        app = WhisperliteApp(config)
        app.start_worker()
        _install_signal_handlers(app)
        _schedule_post_launch_init(app)
        app.run()
        return 0
    except KeyboardInterrupt:
        logger.info("interrupted during init, exiting")
        return 0
    except WhisperliteError as exc:
        logger.exception("fatal error during startup")
        sys.stderr.write(f"whisperlite: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
