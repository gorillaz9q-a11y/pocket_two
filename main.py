from __future__ import annotations

"""Pocket Bot entrypoint for running the Telegram bot."""

from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from pocket_bot.bot import build_application


def main() -> None:
    """Construct the application and begin polling."""
    application = build_application()
    application.run_polling()


if __name__ == "__main__":
    main()
