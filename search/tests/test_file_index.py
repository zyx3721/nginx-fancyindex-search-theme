from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from file_index import (  # noqa: E402
    IndexAlreadyRunningError,
    acquire_index_lock,
    connect,
    index_path_to_url_path,
    index_tree,
    initialize,
    parse_hidden_search_rules,
    request_path_to_index_path,
    parse_exclusion_rules,
    search,
    status,
)
from file_index import fcntl  # noqa: E402


class FileIndexTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name) / "files"
        self.root.mkdir()
        (self.root / "archive").mkdir()
        (self.root / "archive" / "reports").mkdir()
        (self.root / "archive" / "reports" / "Annual Report 2026.pdf").write_text("report")
        (self.root / "notes.txt").write_text("notes")
        self.connection = connect(Path(self.temporary_directory.name) / "index.sqlite3")
        initialize(self.connection)

    def tearDown(self) -> None:
        self.connection.close()
        self.temporary_directory.cleanup()

    def test_searches_descendants_of_current_directory(self) -> None:
        index_tree(self.connection, self.root)

        results = search(self.connection, "/archive/", "report")

        self.assertEqual(
            ["/archive/reports", "/archive/reports/Annual Report 2026.pdf"],
            [item["relative_path"] for item in results],
        )
        self.assertEqual(4, status(self.connection)["indexed_files"])

    def test_reindex_removes_deleted_files(self) -> None:
        index_tree(self.connection, self.root)
        (self.root / "archive" / "reports" / "Annual Report 2026.pdf").unlink()
        index_tree(self.connection, self.root)

        self.assertEqual([], search(self.connection, "/", "annual"))

    def test_rejects_path_traversal(self) -> None:
        index_tree(self.connection, self.root)

        with self.assertRaises(ValueError):
            search(self.connection, "/archive/../", "report")

    def test_maps_subpath_urls_to_the_index_root(self) -> None:
        self.assertEqual("/archive/", request_path_to_index_path("/files/archive/", "/files/"))
        self.assertEqual("/files/archive/report.pdf", index_path_to_url_path("/archive/report.pdf", "/files/"))
        with self.assertRaises(ValueError):
            request_path_to_index_path("/private/", "/files/")

    def test_excludes_configured_directory_and_its_descendants(self) -> None:
        exclusion_rules = parse_exclusion_rules(self.root, ["/archive/"])
        index_tree(self.connection, self.root, exclusion_rules=exclusion_rules)

        self.assertEqual([], search(self.connection, "/", "annual"))
        self.assertEqual(1, status(self.connection)["indexed_files"])

    def test_excludes_configured_file(self) -> None:
        exclusion_rules = parse_exclusion_rules(self.root, ["/notes.txt"])
        index_tree(self.connection, self.root, exclusion_rules=exclusion_rules)

        self.assertEqual([], search(self.connection, "/", "notes"))
        self.assertEqual(3, status(self.connection)["indexed_files"])

    def test_excludes_unprefixed_name_at_any_depth(self) -> None:
        (self.root / "README.md").write_text("root readme")
        (self.root / "archive" / "README.md").write_text("nested readme")
        exclusion_rules = parse_exclusion_rules(self.root, ["README.md"])
        index_tree(self.connection, self.root, exclusion_rules=exclusion_rules)

        self.assertEqual([], search(self.connection, "/", "README"))
        self.assertEqual(4, status(self.connection)["indexed_files"])

    def test_excludes_regular_expression_matches(self) -> None:
        exclusion_rules = parse_exclusion_rules(self.root, [r"^/archive/reports/.*\.pdf$"])
        index_tree(self.connection, self.root, exclusion_rules=exclusion_rules)

        self.assertEqual([], search(self.connection, "/", "annual"))
        self.assertEqual(3, status(self.connection)["indexed_files"])

    def test_hides_directory_tree_outside_its_search_scope(self) -> None:
        hidden_directory = self.root / "vm-template"
        hidden_directory.mkdir()
        (hidden_directory / "private-image.iso").write_text("image")
        visible_directory = self.root / "public"
        visible_directory.mkdir()
        (visible_directory / "vm-template").write_text("visible file")
        index_tree(self.connection, self.root)
        hidden_rules = parse_hidden_search_rules(["vm-template"])

        self.assertEqual([], search(self.connection, "/", "private", hidden_search_rules=hidden_rules))
        self.assertEqual(
            ["/public/vm-template"],
            [
                item["relative_path"]
                for item in search(
                    self.connection,
                    "/",
                    "vm-template",
                    hidden_search_rules=hidden_rules,
                )
            ],
        )
        self.assertEqual(
            ["/vm-template/private-image.iso"],
            [
                item["relative_path"]
                for item in search(
                    self.connection,
                    "/vm-template/",
                    "private",
                    hidden_search_rules=hidden_rules,
                )
            ],
        )

    def test_rejects_invalid_exclusion_regular_expression(self) -> None:
        with self.assertRaises(ValueError):
            parse_exclusion_rules(self.root, ["re:["])

    @unittest.skipIf(fcntl is None, "fcntl locking is only available on POSIX")
    def test_rejects_a_second_index_lock(self) -> None:
        lock_path = self.root / "files.db.lock"
        with ExitStack() as stack:
            stack.enter_context(acquire_index_lock(lock_path, self.root))
            with self.assertRaises(IndexAlreadyRunningError):
                stack.enter_context(acquire_index_lock(lock_path, self.root))


if __name__ == "__main__":
    unittest.main()
