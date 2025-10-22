"""Persistence backends for the Pocket Bot project."""

from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any, Iterable, Mapping, Optional, Protocol, cast
from urllib.parse import parse_qsl, unquote, urlparse

try:  # pragma: no cover - optional dependency for MySQL
    import pymysql  # type: ignore[import]
    from pymysql.cursors import DictCursor as PyMySQLDictCursor  # type: ignore[import]
except ModuleNotFoundError:  # pragma: no cover - handled at runtime
    pymysql = None  # type: ignore
    PyMySQLDictCursor = Any  # type: ignore

if TYPE_CHECKING:  # pragma: no cover - typing helpers
    from pymysql.connections import Connection as PyMySQLConnection  # type: ignore[import]
    from pymysql.cursors import Cursor as PyMySQLCursor  # type: ignore[import]
else:  # pragma: no cover - runtime fallback
    PyMySQLConnection = Any  # type: ignore[misc]
    PyMySQLCursor = Any  # type: ignore[misc]

DB_URL_ENV: str = "POCKET_BOT_DB_URL"
DEFAULT_DB_DIRNAME: str = "data"
DEFAULT_DB_FILENAME: str = "pocket_bot.sqlite3"


class UnsupportedDatabaseError(RuntimeError):
    """Raised when the provided database configuration isn't supported yet."""


class Storage(Protocol):
    """Protocol describing the operations required by the bot."""

    def ensure_defaults(
        self,
        *,
        signals_enabled: bool,
        working_hours: str,
        signals_range: str,
    ) -> None:
        ...

    def get_global_signals(self) -> bool:
        ...

    def set_global_signals(self, enabled: bool) -> None:
        ...

    def get_working_hours(self) -> str:
        ...

    def set_working_hours(self, hours: str) -> None:
        ...

    def get_signal_range(self) -> str:
        ...

    def set_signal_range(self, value: str) -> None:
        ...

    def list_applications(self, status: str | None = None) -> list[dict[str, Any]]:
        ...

    def get_application(self, user_id: int) -> dict[str, Any] | None:
        ...

    def upsert_application(self, application: dict[str, Any]) -> dict[str, Any]:
        ...

    def set_application_status(self, user_id: int, status: str) -> None:
        ...

    def delete_application(self, user_id: int) -> None:
        ...

    def set_user_stage(self, user_id: int, stage: str) -> None:
        ...

    def get_user_stage(self, user_id: int) -> str | None:
        ...

    def list_user_stages(self) -> dict[int, str]:
        ...

    def get_personal_signals(self, user_id: int) -> bool | None:
        ...

    def set_personal_signals(self, user_id: int, enabled: bool) -> None:
        ...

    def list_personal_signals(self) -> dict[int, bool]:
        ...

    def list_signal_recipient_ids(self, completed_stage: str) -> set[int]:
        ...

    def close(self) -> None:
        ...


@dataclass(frozen=True)
class DatabaseConfig:
    """Configuration describing how to connect to the storage backend."""

    url: str

    @classmethod
    def from_env(cls) -> "DatabaseConfig":
        url = os.getenv(DB_URL_ENV)
        if url:
            return cls(url=url)
        root = Path(__file__).resolve().parents[2]
        default_path = root / DEFAULT_DB_DIRNAME / DEFAULT_DB_FILENAME
        return cls(url=f"sqlite:///{default_path}")


def create_storage(config: DatabaseConfig) -> Storage:
    """Create a concrete storage backend from the provided configuration."""

    url = config.url
    if "://" not in url:
        return SQLiteStorage(_resolve_sqlite_path(Path(url)))

    parsed = urlparse(url)
    if parsed.scheme == "sqlite":
        if parsed.path in {":memory:", "/:memory:"} or url.endswith(":memory:"):
            return SQLiteStorage(":memory:")
        path_parts: list[str] = []
        if parsed.netloc:
            path_parts.append(unquote(parsed.netloc))
        if parsed.path:
            parts = [unquote(part) for part in parsed.path.split("/") if part]
            path_parts.extend(parts)
        if not path_parts:
            raise UnsupportedDatabaseError("SQLite URL must include a file path")
        candidate = Path(*path_parts)
        return SQLiteStorage(_resolve_sqlite_path(candidate))

    if parsed.scheme == "mysql":
        if pymysql is None:  # pragma: no cover - runtime guard
            raise UnsupportedDatabaseError(
                "PyMySQL is required for MySQL support. Install it via 'pip install PyMySQL'."
            )

        host = parsed.hostname
        database = parsed.path.lstrip("/") if parsed.path else ""
        if not host or not database:
            raise UnsupportedDatabaseError(
                "MySQL URL must include hostname and database name, e.g. "
                "mysql://user:pass@host:3306/dbname"
            )

        username = unquote(parsed.username) if parsed.username else None
        password = unquote(parsed.password) if parsed.password else None
        if not username:
            raise UnsupportedDatabaseError("MySQL URL must include a username")

        port = parsed.port or 3306
        raw_options = {key: value for key, value in parse_qsl(parsed.query)}
        options: dict[str, Any] = {}
        charset = raw_options.pop("charset", "utf8mb4")
        connect_timeout = raw_options.pop("connect_timeout", None)
        read_timeout = raw_options.pop("read_timeout", None)
        write_timeout = raw_options.pop("write_timeout", None)

        if connect_timeout is not None:
            try:
                options["connect_timeout"] = float(connect_timeout)
            except ValueError:
                raise UnsupportedDatabaseError("connect_timeout must be numeric") from None
        if read_timeout is not None:
            try:
                options["read_timeout"] = float(read_timeout)
            except ValueError:
                raise UnsupportedDatabaseError("read_timeout must be numeric") from None
        if write_timeout is not None:
            try:
                options["write_timeout"] = float(write_timeout)
            except ValueError:
                raise UnsupportedDatabaseError("write_timeout must be numeric") from None

        ssl_params: dict[str, str] = {}
        for key in list(raw_options.keys()):
            if key.startswith("ssl_"):
                ssl_params[key.split("_", 1)[1]] = raw_options.pop(key)

        if ssl_params:
            options["ssl"] = ssl_params

        if raw_options:
            unsupported = ", ".join(sorted(raw_options.keys()))
            raise UnsupportedDatabaseError(
                f"Unsupported MySQL URL options: {unsupported}"
            )

        return MySQLStorage(
            host=host,
            port=port,
            user=username,
            password=password or "",
            database=unquote(database),
            charset=charset,
            options=options,
        )

    raise UnsupportedDatabaseError(
        f"Database scheme '{parsed.scheme}' is not supported yet"
    )


def _resolve_sqlite_path(path: Path) -> Path | str:
    if str(path) == ":memory:":
        return ":memory:"
    if not path.is_absolute():
        root = Path(__file__).resolve().parents[2]
        path = (root / path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _bool_to_int(value: bool) -> int:
    return 1 if value else 0


def _row_to_application(row: sqlite3.Row | Mapping[str, Any]) -> dict[str, Any]:
    data = dict(row)
    data["user_id"] = int(data["user_id"])
    return data


class SQLiteStorage(Storage):
    """SQLite-based implementation of the storage protocol."""

    def __init__(self, path: Path | str):
        self._lock = threading.RLock()
        if isinstance(path, Path):
            path.parent.mkdir(parents=True, exist_ok=True)
            db_path = str(path)
            self._path = path
        else:
            self._path = Path("")
            db_path = path
        self._connection = sqlite3.connect(db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._initialize()

    def close(self) -> None:
        with self._lock:
            if self._connection:
                self._connection.close()

    def __del__(self) -> None:  # pragma: no cover - best effort
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass

    # -- Protocol implementations -------------------------------------------------

    def ensure_defaults(
        self,
        *,
        signals_enabled: bool,
        working_hours: str,
        signals_range: str,
    ) -> None:
        with self._lock:
            self._connection.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                ("signals_enabled", str(_bool_to_int(signals_enabled))),
            )
            self._connection.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                ("working_hours", working_hours),
            )
            self._connection.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                ("signals_range", signals_range),
            )
            self._connection.commit()

    def get_global_signals(self) -> bool:
        row = self._fetchone("SELECT value FROM settings WHERE key = ?", ("signals_enabled",))
        if row is None:
            return False
        return bool(int(row["value"]))

    def set_global_signals(self, enabled: bool) -> None:
        self._execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("signals_enabled", str(_bool_to_int(enabled))),
        )

    def get_working_hours(self) -> str:
        row = self._fetchone("SELECT value FROM settings WHERE key = ?", ("working_hours",))
        return row["value"] if row else ""

    def set_working_hours(self, hours: str) -> None:
        self._execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("working_hours", hours),
        )

    def get_signal_range(self) -> str:
        row = self._fetchone("SELECT value FROM settings WHERE key = ?", ("signals_range",))
        return row["value"] if row else ""

    def set_signal_range(self, value: str) -> None:
        self._execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("signals_range", value),
        )

    def list_applications(self, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            rows = self._fetchall(
                "SELECT * FROM applications WHERE status = ? ORDER BY user_id",
                (status,),
            )
        else:
            rows = self._fetchall("SELECT * FROM applications ORDER BY user_id")
        return [_row_to_application(row) for row in rows]

    def get_application(self, user_id: int) -> dict[str, Any] | None:
        row = self._fetchone("SELECT * FROM applications WHERE user_id = ?", (user_id,))
        return _row_to_application(row) if row else None

    def upsert_application(self, application: dict[str, Any]) -> dict[str, Any]:
        user_id = int(application["user_id"])
        now = _utcnow()
        with self._lock:
            cur = self._connection.execute(
                "SELECT created_at FROM applications WHERE user_id = ?",
                (user_id,),
            )
            row = cur.fetchone()
            created_at = row["created_at"] if row else now
            payload: dict[str, Any] = {
                "user_id": user_id,
                "pocket_id": application.get("pocket_id", ""),
                "status": application.get("status", "pending"),
                "language": application.get("language", "ru"),
                "first_name": application.get("first_name"),
                "last_name": application.get("last_name"),
                "username": application.get("username"),
                "created_at": created_at,
                "updated_at": now,
            }
            self._connection.execute(
                """
                INSERT INTO applications (
                    user_id, pocket_id, status, language, first_name, last_name, username,
                    created_at, updated_at
                ) VALUES (:user_id, :pocket_id, :status, :language, :first_name, :last_name,
                          :username, :created_at, :updated_at)
                ON CONFLICT(user_id) DO UPDATE SET
                    pocket_id = excluded.pocket_id,
                    status = excluded.status,
                    language = excluded.language,
                    first_name = excluded.first_name,
                    last_name = excluded.last_name,
                    username = excluded.username,
                    created_at = :created_at,
                    updated_at = excluded.updated_at
                """,
                payload,
            )
            self._connection.commit()
            refreshed = self._connection.execute(
                "SELECT * FROM applications WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        assert refreshed is not None
        return _row_to_application(refreshed)

    def set_application_status(self, user_id: int, status: str) -> None:
        self._execute(
            "UPDATE applications SET status = ?, updated_at = ? WHERE user_id = ?",
            (status, _utcnow(), user_id),
        )

    def delete_application(self, user_id: int) -> None:
        self._execute("DELETE FROM applications WHERE user_id = ?", (user_id,))

    def set_user_stage(self, user_id: int, stage: str) -> None:
        self._execute(
            "INSERT INTO user_stages (user_id, stage) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET stage = excluded.stage",
            (user_id, stage),
        )

    def get_user_stage(self, user_id: int) -> str | None:
        row = self._fetchone("SELECT stage FROM user_stages WHERE user_id = ?", (user_id,))
        return row["stage"] if row else None

    def list_user_stages(self) -> dict[int, str]:
        rows = self._fetchall("SELECT user_id, stage FROM user_stages")
        return {int(row["user_id"]): row["stage"] for row in rows}

    def get_personal_signals(self, user_id: int) -> bool | None:
        row = self._fetchone(
            "SELECT enabled FROM personal_signals WHERE user_id = ?",
            (user_id,),
        )
        if row is None:
            return None
        return bool(int(row["enabled"]))

    def set_personal_signals(self, user_id: int, enabled: bool) -> None:
        self._execute(
            "INSERT INTO personal_signals (user_id, enabled) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET enabled = excluded.enabled",
            (user_id, _bool_to_int(enabled)),
        )

    def list_personal_signals(self) -> dict[int, bool]:
        rows = self._fetchall("SELECT user_id, enabled FROM personal_signals")
        return {int(row["user_id"]): bool(int(row["enabled"])) for row in rows}

    def list_signal_recipient_ids(self, completed_stage: str) -> set[int]:
        rows = self._fetchall(
            """
            WITH eligible AS (
                SELECT user_id FROM applications WHERE status = 'approved'
                UNION
                SELECT user_id FROM user_stages WHERE stage = ?
            )
            SELECT DISTINCT e.user_id
            FROM eligible e
            LEFT JOIN personal_signals ps ON ps.user_id = e.user_id
            WHERE COALESCE(ps.enabled, 1) = 1
            """,
            (completed_stage,),
        )
        return {int(row["user_id"]) for row in rows}

    # -- Internal helpers --------------------------------------------------------

    def _initialize(self) -> None:
        with self._lock:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS applications (
                    user_id INTEGER PRIMARY KEY,
                    pocket_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    language TEXT NOT NULL,
                    first_name TEXT,
                    last_name TEXT,
                    username TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS user_stages (
                    user_id INTEGER PRIMARY KEY,
                    stage TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS personal_signals (
                    user_id INTEGER PRIMARY KEY,
                    enabled INTEGER NOT NULL
                );
                """
            )
            self._connection.commit()

    def _execute(self, query: str, params: Iterable[Any] = ()) -> None:
        with self._lock:
            self._connection.execute(query, tuple(params))
            self._connection.commit()

    def _fetchall(self, query: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            cursor = self._connection.execute(query, tuple(params))
            rows = cursor.fetchall()
        return rows

    def _fetchone(self, query: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            cursor = self._connection.execute(query, tuple(params))
            row = cursor.fetchone()
        return row


class MySQLStorage(Storage):
    """MySQL-based implementation of the storage protocol."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        charset: str = "utf8mb4",
        options: Optional[dict[str, Any]] = None,
    ) -> None:
        if pymysql is None:  # pragma: no cover - runtime guard
            raise UnsupportedDatabaseError(
                "PyMySQL is required for MySQL support. Install it via 'pip install PyMySQL'."
            )

        self._lock = threading.RLock()
        connect_kwargs: dict[str, Any] = {
            "host": host,
            "port": int(port),
            "user": user,
            "password": password,
            "database": database,
            "charset": charset,
            "cursorclass": PyMySQLDictCursor,
            "autocommit": False,
        }
        if options:
            connect_kwargs.update(options)

        self._connection = pymysql.connect(**connect_kwargs)
        self._initialize()

    def close(self) -> None:
        with self._lock:
            if self._connection:
                self._connection.close()

    def __del__(self) -> None:  # pragma: no cover - best effort
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass

    def ensure_defaults(
        self,
        *,
        signals_enabled: bool,
        working_hours: str,
        signals_range: str,
    ) -> None:
        with self._cursor() as cursor:
            cursor.execute(
                "INSERT IGNORE INTO settings (`key`, `value`) VALUES (%s, %s)",
                ("signals_enabled", str(_bool_to_int(signals_enabled))),
            )
            cursor.execute(
                "INSERT IGNORE INTO settings (`key`, `value`) VALUES (%s, %s)",
                ("working_hours", working_hours),
            )
            cursor.execute(
                "INSERT IGNORE INTO settings (`key`, `value`) VALUES (%s, %s)",
                ("signals_range", signals_range),
            )
            self._connection.commit()

    def get_global_signals(self) -> bool:
        row = self._fetchone(
            "SELECT `value` FROM settings WHERE `key` = %s",
            ("signals_enabled",),
        )
        if not row:
            return False
        return bool(int(row["value"]))

    def set_global_signals(self, enabled: bool) -> None:
        self._execute(
            "INSERT INTO settings (`key`, `value`) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE `value` = VALUES(`value`)",
            ("signals_enabled", str(_bool_to_int(enabled))),
        )

    def get_working_hours(self) -> str:
        row = self._fetchone(
            "SELECT `value` FROM settings WHERE `key` = %s",
            ("working_hours",),
        )
        return row["value"] if row else ""

    def set_working_hours(self, hours: str) -> None:
        self._execute(
            "INSERT INTO settings (`key`, `value`) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE `value` = VALUES(`value`)",
            ("working_hours", hours),
        )

    def get_signal_range(self) -> str:
        row = self._fetchone(
            "SELECT `value` FROM settings WHERE `key` = %s",
            ("signals_range",),
        )
        return row["value"] if row else ""

    def set_signal_range(self, value: str) -> None:
        self._execute(
            "INSERT INTO settings (`key`, `value`) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE `value` = VALUES(`value`)",
            ("signals_range", value),
        )

    def list_applications(self, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            rows = self._fetchall(
                "SELECT * FROM applications WHERE status = %s ORDER BY user_id",
                (status,),
            )
        else:
            rows = self._fetchall("SELECT * FROM applications ORDER BY user_id")
        return [_row_to_application(row) for row in rows]

    def get_application(self, user_id: int) -> dict[str, Any] | None:
        row = self._fetchone("SELECT * FROM applications WHERE user_id = %s", (user_id,))
        return _row_to_application(row) if row else None

    def upsert_application(self, application: dict[str, Any]) -> dict[str, Any]:
        user_id = int(application["user_id"])
        now = _utcnow()
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT created_at FROM applications WHERE user_id = %s",
                (user_id,),
            )
            row = cast(dict[str, Any] | None, cursor.fetchone())
            created_at = row["created_at"] if row else now
            payload: dict[str, Any] = {
                "user_id": user_id,
                "pocket_id": application.get("pocket_id", ""),
                "status": application.get("status", "pending"),
                "language": application.get("language", "ru"),
                "first_name": application.get("first_name"),
                "last_name": application.get("last_name"),
                "username": application.get("username"),
                "created_at": created_at,
                "updated_at": now,
            }
            cursor.execute(
                """
                INSERT INTO applications (
                    user_id, pocket_id, status, language, first_name, last_name,
                    username, created_at, updated_at
                ) VALUES (
                    %(user_id)s, %(pocket_id)s, %(status)s, %(language)s, %(first_name)s,
                    %(last_name)s, %(username)s, %(created_at)s, %(updated_at)s
                )
                ON DUPLICATE KEY UPDATE
                    pocket_id = VALUES(pocket_id),
                    status = VALUES(status),
                    language = VALUES(language),
                    first_name = VALUES(first_name),
                    last_name = VALUES(last_name),
                    username = VALUES(username),
                    created_at = %(created_at)s,
                    updated_at = VALUES(updated_at)
                """,
                payload,
            )
            self._connection.commit()
            cursor.execute("SELECT * FROM applications WHERE user_id = %s", (user_id,))
            refreshed = cast(dict[str, Any] | None, cursor.fetchone())
        assert refreshed is not None
        return _row_to_application(refreshed)

    def set_application_status(self, user_id: int, status: str) -> None:
        self._execute(
            "UPDATE applications SET status = %s, updated_at = %s WHERE user_id = %s",
            (status, _utcnow(), user_id),
        )

    def delete_application(self, user_id: int) -> None:
        self._execute("DELETE FROM applications WHERE user_id = %s", (user_id,))

    def set_user_stage(self, user_id: int, stage: str) -> None:
        self._execute(
            "INSERT INTO user_stages (user_id, stage) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE stage = VALUES(stage)",
            (user_id, stage),
        )

    def get_user_stage(self, user_id: int) -> str | None:
        row = self._fetchone("SELECT stage FROM user_stages WHERE user_id = %s", (user_id,))
        return row["stage"] if row else None

    def list_user_stages(self) -> dict[int, str]:
        rows = self._fetchall("SELECT user_id, stage FROM user_stages")
        return {int(row["user_id"]): row["stage"] for row in rows}

    def get_personal_signals(self, user_id: int) -> bool | None:
        row = self._fetchone(
            "SELECT enabled FROM personal_signals WHERE user_id = %s",
            (user_id,),
        )
        if row is None:
            return None
        return bool(int(row["enabled"]))

    def set_personal_signals(self, user_id: int, enabled: bool) -> None:
        self._execute(
            "INSERT INTO personal_signals (user_id, enabled) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE enabled = VALUES(enabled)",
            (user_id, _bool_to_int(enabled)),
        )

    def list_personal_signals(self) -> dict[int, bool]:
        rows = self._fetchall("SELECT user_id, enabled FROM personal_signals")
        return {int(row["user_id"]): bool(int(row["enabled"])) for row in rows}

    def list_signal_recipient_ids(self, completed_stage: str) -> set[int]:
        rows = self._fetchall(
            """
            WITH eligible AS (
                SELECT user_id FROM applications WHERE status = 'approved'
                UNION
                SELECT user_id FROM user_stages WHERE stage = %s
            )
            SELECT DISTINCT e.user_id
            FROM eligible e
            LEFT JOIN personal_signals ps ON ps.user_id = e.user_id
            WHERE COALESCE(ps.enabled, 1) = 1
            """,
            (completed_stage,),
        )
        return {int(row["user_id"]) for row in rows}

    # -- Internal helpers ----------------------------------------------------

    def _cursor(self):
        self._lock.acquire()
        try:
            self._connection.ping(reconnect=True)
            return _CursorContext(self._lock, self._connection.cursor())
        except Exception:
            self._lock.release()
            raise

    def _execute(self, query: str, params: Iterable[Any] = ()) -> None:
        with self._cursor() as cursor:
            cursor.execute(query, tuple(params))
            self._connection.commit()

    def _fetchall(self, query: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def _fetchone(self, query: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            cursor.execute(query, tuple(params))
            row = cursor.fetchone()
        return dict(row) if row else None

    def _initialize(self) -> None:
        with self._cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    `key` VARCHAR(191) PRIMARY KEY,
                    `value` TEXT NOT NULL
                )
                ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS applications (
                    user_id BIGINT UNSIGNED PRIMARY KEY,
                    pocket_id VARCHAR(191) NOT NULL,
                    status VARCHAR(50) NOT NULL,
                    language VARCHAR(10) NOT NULL,
                    first_name VARCHAR(191),
                    last_name VARCHAR(191),
                    username VARCHAR(191),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_stages (
                    user_id BIGINT UNSIGNED PRIMARY KEY,
                    stage VARCHAR(50) NOT NULL
                )
                ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS personal_signals (
                    user_id BIGINT UNSIGNED PRIMARY KEY,
                    enabled TINYINT(1) NOT NULL
                )
                ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            self._connection.commit()


class _CursorContext:
    """Context manager wrapping a PyMySQL cursor with thread locking."""

    def __init__(self, lock: threading.RLock, cursor: Any) -> None:
        self._lock = lock
        self._cursor = cursor

    def __enter__(self) -> Any:
        return self._cursor

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            self._cursor.close()
        finally:
            self._lock.release()



__all__ = [
    "DatabaseConfig",
    "Storage",
    "create_storage",
    "SQLiteStorage",
    "MySQLStorage",
    "UnsupportedDatabaseError",
]
