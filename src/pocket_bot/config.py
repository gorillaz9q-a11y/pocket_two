"""Configuration helpers for the Pocket Bot project."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Optional, Set

_DEFAULT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
_TOKEN_ENV_KEYS: tuple[str, ...] = (
    "POCKET_BOT_TOKEN",
    "TELEGRAM_BOT_TOKEN",
)
_ADMIN_IDS_KEYS: tuple[str, ...] = (
    "POCKET_BOT_ADMIN_IDS",
    "TELEGRAM_ADMIN_IDS",
)
_DEFAULT_ADMIN_IDS: frozenset[int] = frozenset({5_542_569_488})


def _load_env_file(path: Path) -> None:
    """Populate ``os.environ`` with values from a simple ``.env`` file."""
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", maxsplit=1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _first_env_value(keys: Iterable[str]) -> Optional[str]:
    for key in keys:
        value = os.getenv(key)
        if value:
            return value
    return None


def get_bot_token(*, env_file: Optional[Path] = None) -> str:
    """Return the Telegram bot token, loading from ``.env`` when needed."""
    env_path = env_file or _DEFAULT_ENV_FILE
    _load_env_file(env_path)

    token = _first_env_value(_TOKEN_ENV_KEYS)
    if not token:
        joined = ", ".join(_TOKEN_ENV_KEYS)
        raise RuntimeError(
            "Telegram bot token is missing. Set one of the following environment "
            f"variables: {joined}. Optionally, create a .env file with the token"
        )
    return token


def get_admin_ids(*, env_file: Optional[Path] = None) -> Set[int]:
    """Return a set of Telegram user IDs that are treated as administrators."""
    env_path = env_file or _DEFAULT_ENV_FILE
    _load_env_file(env_path)

    raw_value = _first_env_value(_ADMIN_IDS_KEYS)
    if not raw_value:
        return set(_DEFAULT_ADMIN_IDS)

    admin_ids: Set[int] = set()
    for chunk in raw_value.replace(";", ",").split(","):
        item = chunk.strip()
        if not item:
            continue
        try:
            admin_ids.add(int(item))
        except ValueError as exc:  # pragma: no cover - configuration error path
            raise ValueError(
                "Invalid Telegram admin ID in environment variable: "
                f"'{item}'. IDs must be integers"
            ) from exc

    return admin_ids.union(_DEFAULT_ADMIN_IDS)
