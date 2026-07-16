#!/usr/bin/env python3
"""Local-only HTTP API for the Fancyindex recursive-search index."""

from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from file_index import (
    HiddenSearchRules,
    connect,
    index_path_to_url_path,
    initialize,
    normalize_request_path,
    parse_hidden_search_rules,
    request_path_to_index_path,
    search,
    status,
)


class SearchHandler(BaseHTTPRequestHandler):
    database_path: Path
    url_prefix: str
    hidden_search_rules: HiddenSearchRules

    def do_GET(self) -> None:  # noqa: N802
        request = urlparse(self.path)
        if request.path == "/health":
            return self._handle_health()
        if request.path == "/search":
            return self._handle_search(request.query)
        self._write_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def _handle_health(self) -> None:
        try:
            with closing(connect(self.database_path)) as connection:
                initialize(connection)
                self._write_json(HTTPStatus.OK, {"ok": True, **status(connection)})
        except sqlite3.Error:
            self._write_json(HTTPStatus.SERVICE_UNAVAILABLE, {"ok": False})

    def _handle_search(self, query_string: str) -> None:
        parameters = parse_qs(query_string, keep_blank_values=True)
        current_path = parameters.get("path", [""])[0]
        keyword = parameters.get("q", [""])[0]
        try:
            index_path = request_path_to_index_path(current_path, self.url_prefix)
            with closing(connect(self.database_path)) as connection:
                initialize(connection)
                results = search(
                    connection,
                    index_path,
                    keyword,
                    self.hidden_search_rules,
                )
            for result in results:
                result["relative_path"] = index_path_to_url_path(
                    str(result["relative_path"]), self.url_prefix
                )
        except (ValueError, sqlite3.Error) as error:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        self._write_json(HTTPStatus.OK, {"results": results})

    def _write_json(self, status_code: HTTPStatus, body: dict[str, object]) -> None:
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the Fancyindex recursive search API")
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--url-prefix",
        default="/",
        help="public URL path mapped to the indexed root, for example /files/",
    )
    parser.add_argument(
        "--hide",
        action="append",
        default=[],
        metavar="NAME_OR_ROOT_PATH",
        help="hide a directory tree from parent search scopes, repeatable",
    )
    arguments = parser.parse_args()
    SearchHandler.database_path = arguments.database
    try:
        SearchHandler.url_prefix = normalize_request_path(arguments.url_prefix)
        SearchHandler.hidden_search_rules = parse_hidden_search_rules(arguments.hide)
    except ValueError as error:
        parser.error(str(error))
    server = ThreadingHTTPServer((arguments.host, arguments.port), SearchHandler)
    print(f"search API listening on http://{arguments.host}:{arguments.port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
