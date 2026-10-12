"""Atomic writes survive a short lock on the target file (Windows: scanner, indexer, a reader)."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from navigator.ingestion import fsutil


class AtomicWriteTests(unittest.TestCase):
    def test_a_short_lock_on_the_target_is_waited_out(self):
        real_replace, calls = os.replace, {"n": 0}

        def flaky(source, target):
            calls["n"] += 1
            if calls["n"] <= 3:
                raise PermissionError(5, "Access is denied")
            return real_replace(source, target)

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            target = Path(tmp) / "audit.jsonl"
            with mock.patch.object(fsutil.os, "replace", flaky), mock.patch.object(fsutil.time, "sleep"):
                fsutil.atomic_write_text(target, "row\n")
            self.assertEqual(target.read_text(encoding="utf-8"), "row\n")
            self.assertEqual(calls["n"], 4)
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["audit.jsonl"])  # no temp file left behind

    def test_a_lock_that_stays_is_still_an_error_and_leaves_no_temp_file(self):
        def locked(source, target):
            raise PermissionError(5, "Access is denied")

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            target = Path(tmp) / "audit.jsonl"
            with mock.patch.object(fsutil.os, "replace", locked), mock.patch.object(fsutil.time, "sleep"):
                with self.assertRaises(PermissionError):
                    fsutil.atomic_write_text(target, "row\n")
            self.assertEqual(list(Path(tmp).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
