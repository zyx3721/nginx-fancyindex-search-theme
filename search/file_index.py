#!/usr/bin/env python3
"""Build and query a SQLite FTS5 index for an Nginx file tree."""

from __future__ import annotations

import argparse
import errno
import os
import re
import sqlite3
import socket
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows is supported for local tests only.
    fcntl = None

MAX_QUERY_LENGTH = 120
SCHEMA_VERSION = "3"


@dataclass(frozen=True)
class IndexedFile:
    relative_path: str
    parent_path: str
    name: str
    is_dir: int
    size: int
    modified_ns: int


@dataclass(frozen=True)
class ExclusionRules:
    rooted_paths: set[Path]
    names: set[str]
    patterns: list[re.Pattern]


@dataclass(frozen=True)
class HiddenSearchRules:
    rooted_paths: set[str]
    names: set[str]


class IndexAlreadyRunningError(RuntimeError):
    pass


def connect(database_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


@contextmanager
def acquire_index_lock(lock_path: Path, root: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = lock_path.open("a+", encoding="utf-8")
    if fcntl is None:
        try:
            yield
        finally:
            lock_file.close()
        return

    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        if error.errno not in {errno.EACCES, errno.EAGAIN}:
            lock_file.close()
            raise
        lock_file.seek(0)
        holder = lock_file.read().strip() or "holder metadata is unavailable"
        lock_file.close()
        raise IndexAlreadyRunningError(
            f"another index process holds {lock_path}: {holder}"
        ) from error

    try:
        lock_file.seek(0)
        lock_file.truncate()
        lock_file.write(
            "pid={pid} host={host} started_at={started_at} root={root}\n".format(
                pid=os.getpid(),
                host=socket.gethostname(),
                started_at=datetime.now(timezone.utc).isoformat(),
                root=root,
            )
        )
        lock_file.flush()
        os.fsync(lock_file.fileno())
        yield
    finally:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


def initialize(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY,
            relative_path TEXT NOT NULL UNIQUE,
            parent_path TEXT NOT NULL,
            name TEXT NOT NULL,
            is_dir INTEGER NOT NULL CHECK (is_dir IN (0, 1)),
            size INTEGER NOT NULL,
            modified_ns INTEGER NOT NULL,
            last_seen_scan INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS files_parent_path_idx ON files(parent_path);
        """
    )
    if not _uses_trigram_tokenizer(connection):
        _rebuild_fts_index(connection)
    elif not _uses_change_only_fts_update_trigger(connection):
        _rebuild_fts_triggers(connection)
    connection.execute(
        "INSERT OR REPLACE INTO metadata(key, value) VALUES ('schema_version', ?)",
        (SCHEMA_VERSION,),
    )
    connection.commit()


def _uses_trigram_tokenizer(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'files_fts'"
    ).fetchone()
    return row is not None and "tokenize='trigram'" in row["sql"].lower()


def _uses_change_only_fts_update_trigger(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = 'files_after_update'"
    ).fetchone()
    return row is not None and (
        "when old.name is not new.name or old.relative_path is not new.relative_path"
        in row["sql"].lower()
    )


def _rebuild_fts_index(connection: sqlite3.Connection) -> None:
    # Tokenizer changes require recreating the FTS table; files metadata remains intact.
    connection.executescript(
        """
        DROP TRIGGER IF EXISTS files_after_insert;
        DROP TRIGGER IF EXISTS files_after_delete;
        DROP TRIGGER IF EXISTS files_after_update;
        DROP TABLE IF EXISTS files_fts;

        CREATE VIRTUAL TABLE files_fts USING fts5(
            name,
            relative_path,
            content='files',
            content_rowid='id',
            tokenize='trigram'
        );
        """
    )
    _rebuild_fts_triggers(connection)
    connection.execute("INSERT INTO files_fts(files_fts) VALUES ('rebuild')")


def _rebuild_fts_triggers(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        DROP TRIGGER IF EXISTS files_after_insert;
        DROP TRIGGER IF EXISTS files_after_delete;
        DROP TRIGGER IF EXISTS files_after_update;

        CREATE TRIGGER files_after_insert AFTER INSERT ON files BEGIN
            INSERT INTO files_fts(rowid, name, relative_path)
            VALUES (new.id, new.name, new.relative_path);
        END;

        CREATE TRIGGER files_after_delete AFTER DELETE ON files BEGIN
            INSERT INTO files_fts(files_fts, rowid, name, relative_path)
            VALUES ('delete', old.id, old.name, old.relative_path);
        END;

        CREATE TRIGGER files_after_update AFTER UPDATE OF name, relative_path ON files
        WHEN old.name IS NOT new.name OR old.relative_path IS NOT new.relative_path
        BEGIN
            INSERT INTO files_fts(files_fts, rowid, name, relative_path)
            VALUES ('delete', old.id, old.name, old.relative_path);
            INSERT INTO files_fts(rowid, name, relative_path)
            VALUES (new.id, new.name, new.relative_path);
        END;
        """
    )


def normalize_request_path(value: str) -> str:
    if not value or "\x00" in value or "\\" in value:
        raise ValueError("path must be a non-empty POSIX path")
    if not value.startswith("/"):
        raise ValueError("path must start with '/'")

    parts = [part for part in value.split("/") if part]
    if any(part in {".", ".."} for part in parts):
        raise ValueError("path traversal is not allowed")
    return "/" + "/".join(parts) + ("/" if parts else "")


def request_path_to_index_path(request_path: str, url_prefix: str) -> str:
    request_path = normalize_request_path(request_path)
    url_prefix = normalize_request_path(url_prefix)
    if url_prefix == "/":
        return request_path
    if not request_path.startswith(url_prefix):
        raise ValueError("path is outside the configured URL prefix")
    suffix = request_path[len(url_prefix) :]
    return "/" + suffix


def index_path_to_url_path(relative_path: str, url_prefix: str) -> str:
    if not relative_path or "\x00" in relative_path or "\\" in relative_path:
        raise ValueError("relative path must be a non-empty POSIX path")
    if not relative_path.startswith("/"):
        raise ValueError("relative path must start with '/'")
    parts = [part for part in relative_path.split("/") if part]
    if any(part in {".", ".."} for part in parts):
        raise ValueError("path traversal is not allowed")
    relative_path = "/" + "/".join(parts)
    url_prefix = normalize_request_path(url_prefix)
    if url_prefix == "/":
        return relative_path
    return url_prefix.rstrip("/") + relative_path


def make_fts_query(query: str) -> str:
    if not isinstance(query, str):
        raise ValueError("query must be text")
    query = query.strip()
    if not query or len(query) > MAX_QUERY_LENGTH:
        raise ValueError(f"query must contain 1-{MAX_QUERY_LENGTH} characters")

    terms = re.findall(r"[\w.-]+", query, flags=re.UNICODE)
    if not terms:
        raise ValueError("query does not contain searchable characters")
    return " AND ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)


def parse_exclusion_rules(root: Path, excludes: list[str]) -> ExclusionRules:
    root = root.resolve(strict=True)
    rooted_paths: set[Path] = set()
    names: set[str] = set()
    patterns: list[re.Pattern] = []
    for exclude in excludes:
        if not exclude or "\x00" in exclude:
            raise ValueError("exclusion must be non-empty text")
        if exclude.startswith("re:"):
            pattern = exclude[3:]
        elif exclude.startswith("^") or exclude.endswith("$"):
            pattern = exclude
        else:
            pattern = None

        if pattern is not None:
            if not pattern:
                raise ValueError("regular expression exclusion must not be empty")
            try:
                patterns.append(re.compile(pattern))
            except re.error as error:
                raise ValueError(f"invalid exclusion pattern {pattern!r}: {error}") from error
            continue

        if not exclude.startswith("/"):
            if "/" in exclude or "\\" in exclude or exclude in {".", ".."}:
                raise ValueError("unprefixed exclusion must be a file or directory name")
            names.add(exclude)
            continue

        relative_path = normalize_request_path(exclude)
        if relative_path == "/":
            raise ValueError("excluding the index root is not allowed")
        rooted_paths.add((root / relative_path.lstrip("/")).resolve(strict=False))
    return ExclusionRules(rooted_paths, names, patterns)


def parse_hidden_search_rules(values: list[str]) -> HiddenSearchRules:
    rooted_paths: set[str] = set()
    names: set[str] = set()
    for value in values:
        if not value or "\x00" in value:
            raise ValueError("hidden search root must be non-empty text")
        if value.startswith("/"):
            root_path = normalize_request_path(value).rstrip("/")
            if not root_path:
                raise ValueError("hiding the index root is not allowed")
            rooted_paths.add(root_path)
            continue
        if "/" in value or "\\" in value or value in {".", ".."}:
            raise ValueError("unprefixed hidden search root must be a directory name")
        names.add(value)
    return HiddenSearchRules(rooted_paths, names)


def _to_relative_path(root: Path, path: Path) -> str:
    relative = path.relative_to(root).as_posix()
    return "/" + relative


def _matches_exclusion(path: Path, relative_path: str, rules: ExclusionRules) -> bool:
    if path.resolve(strict=False) in rules.rooted_paths:
        return True

    name = relative_path.rsplit("/", 1)[-1]
    if name in rules.names:
        return True

    return any(pattern.search(relative_path) or pattern.search(name) for pattern in rules.patterns)


def walk_files(root: Path, exclusion_rules: ExclusionRules) -> Iterator[IndexedFile]:
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError as error:
            raise RuntimeError(f"cannot read directory {directory}: {error}") from error

        for entry in entries:
            path = Path(entry.path)
            if entry.is_symlink():
                continue
            relative_path = _to_relative_path(root, path)
            if _matches_exclusion(path, relative_path, exclusion_rules):
                continue
            try:
                stat = entry.stat(follow_symlinks=False)
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError as error:
                raise RuntimeError(f"cannot stat {path}: {error}") from error

            parent_path = relative_path.rsplit("/", 1)[0] + "/"
            yield IndexedFile(
                relative_path=relative_path,
                parent_path=parent_path,
                name=entry.name,
                is_dir=int(is_dir),
                size=0 if is_dir else stat.st_size,
                modified_ns=stat.st_mtime_ns,
            )
            if is_dir:
                pending.append(path)


UPSERT_SQL = """
INSERT INTO files(relative_path, parent_path, name, is_dir, size, modified_ns, last_seen_scan)
VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(relative_path) DO UPDATE SET
    parent_path = excluded.parent_path,
    name = excluded.name,
    is_dir = excluded.is_dir,
    size = excluded.size,
    modified_ns = excluded.modified_ns,
    last_seen_scan = excluded.last_seen_scan
"""


def index_tree(
    connection: sqlite3.Connection,
    root: Path,
    batch_size: int = 2_000,
    exclusion_rules: ExclusionRules | None = None,
) -> int:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"index root is not a directory: {root}")
    if batch_size < 1:
        raise ValueError("batch_size must be positive")

    exclusion_rules = exclusion_rules or ExclusionRules(set(), set(), [])

    scan_id = time.time_ns()
    row_count = 0
    batch: list[tuple[object, ...]] = []
    try:
        for item in walk_files(root, exclusion_rules):
            batch.append(
                (
                    item.relative_path,
                    item.parent_path,
                    item.name,
                    item.is_dir,
                    item.size,
                    item.modified_ns,
                    scan_id,
                )
            )
            if len(batch) >= batch_size:
                connection.executemany(UPSERT_SQL, batch)
                connection.commit()
                row_count += len(batch)
                batch.clear()
        if batch:
            connection.executemany(UPSERT_SQL, batch)
            connection.commit()
            row_count += len(batch)

        # Delete stale rows only after a complete traversal. Earlier batch commits
        # keep the search API readable during large scans without losing old data.
        with connection:
            connection.execute("DELETE FROM files WHERE last_seen_scan <> ?", (scan_id,))
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES ('indexed_root', ?)",
                (str(root),),
            )
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES ('last_indexed_at', ?)",
                (str(int(time.time())),),
            )
    except Exception:
        connection.rollback()
        raise
    return row_count


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _is_within_hidden_root(current_path: str, root_path: str) -> bool:
    return current_path == root_path or current_path.startswith(root_path + "/")


def _is_within_hidden_name(current_path: str, name: str) -> bool:
    return name in [part for part in current_path.split("/") if part]


def _hidden_search_conditions(
    current_path: str, rules: HiddenSearchRules
) -> tuple[list[str], list[object]]:
    conditions: list[str] = []
    parameters: list[object] = []

    for root_path in rules.rooted_paths:
        if _is_within_hidden_root(current_path, root_path):
            continue
        conditions.append(
            "NOT ((files.relative_path = ? AND files.is_dir = 1) "
            "OR files.relative_path LIKE ? ESCAPE '\\')"
        )
        parameters.extend((root_path, _escape_like(root_path) + "/%"))

    for name in rules.names:
        if _is_within_hidden_name(current_path, name):
            continue
        escaped_name = _escape_like(name)
        conditions.append(
            "NOT ((files.relative_path = ? AND files.is_dir = 1) "
            "OR files.relative_path LIKE ? ESCAPE '\\' "
            "OR (files.relative_path LIKE ? ESCAPE '\\' AND files.is_dir = 1) "
            "OR files.relative_path LIKE ? ESCAPE '\\')"
        )
        parameters.extend(
            (
                "/" + name,
                "/" + escaped_name + "/%",
                "%/" + escaped_name,
                "%/" + escaped_name + "/%",
            )
        )

    return conditions, parameters


def search(
    connection: sqlite3.Connection,
    current_path: str,
    query: str,
    hidden_search_rules: HiddenSearchRules | None = None,
) -> list[dict[str, object]]:
    current_path = normalize_request_path(current_path)
    fts_query = make_fts_query(query)
    path_prefix = current_path + "%"
    hidden_search_rules = hidden_search_rules or HiddenSearchRules(set(), set())
    hidden_conditions, hidden_parameters = _hidden_search_conditions(
        current_path, hidden_search_rules
    )
    where_conditions = ["files_fts MATCH ?", "files.relative_path LIKE ? ESCAPE '\\'"]
    where_conditions.extend(hidden_conditions)
    parameters: list[object] = [fts_query, path_prefix]
    parameters.extend(hidden_parameters)

    rows = connection.execute(
        f"""
        SELECT files.relative_path, files.parent_path, files.name, files.is_dir,
               files.size, files.modified_ns
        FROM files_fts
        JOIN files ON files.id = files_fts.rowid
        WHERE {' AND '.join(where_conditions)}
        ORDER BY bm25(files_fts), files.is_dir DESC, files.name COLLATE NOCASE
        """,
        parameters,
    ).fetchall()
    return [dict(row) for row in rows]


def status(connection: sqlite3.Connection) -> dict[str, object]:
    metadata = {
        row["key"]: row["value"]
        for row in connection.execute("SELECT key, value FROM metadata").fetchall()
    }
    return {
        "indexed_files": connection.execute("SELECT COUNT(*) FROM files").fetchone()[0],
        "indexed_root": metadata.get("indexed_root"),
        "last_indexed_at": metadata.get("last_indexed_at"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Index an Nginx file tree into SQLite FTS5")
    parser.add_argument("--root", required=True, type=Path, help="directory exposed by Nginx")
    parser.add_argument("--database", required=True, type=Path, help="SQLite index path")
    parser.add_argument("--batch-size", type=int, default=2_000)
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="PATH_OR_PATTERN",
        help="rooted path, bare name, or regular expression to skip; repeatable",
    )
    arguments = parser.parse_args()

    try:
        root = arguments.root.resolve(strict=True)
        lock_path = Path(f"{arguments.database}.lock")
        with acquire_index_lock(lock_path, root):
            print(f"INFO: index lock acquired: {lock_path}", file=sys.stderr)
            connection = connect(arguments.database)
            try:
                initialize(connection)
                exclusion_rules = parse_exclusion_rules(root, arguments.exclude)
                row_count = index_tree(
                    connection,
                    root,
                    arguments.batch_size,
                    exclusion_rules,
                )
                print(f"indexed {row_count} entries")
            finally:
                connection.close()
    except IndexAlreadyRunningError as error:
        print(f"ERROR: index run skipped: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
