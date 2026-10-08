import tempfile
import unittest
from pathlib import Path

from navigator.services.live import clear_quarantine


class QuarantineClearTests(unittest.TestCase):
    def test_a_rerun_with_the_same_run_id_starts_without_the_old_findings(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            folder = Path(tmp) / "quarantine"
            folder.mkdir()
            stale, other = folder / "extract-20261007T120000Z.jsonl", folder / "extract-20261008T120000Z.jsonl"
            stale.write_text("{}\n", encoding="utf-8")
            other.write_text("{}\n", encoding="utf-8")
            clear_quarantine(Path(tmp), "extract-20261007T120000Z")
            self.assertFalse(stale.exists())
            self.assertTrue(other.exists(), "another run's findings are untouched")
            clear_quarantine(Path(tmp), "extract-20261007T120000Z")  # nothing to remove: no error


if __name__ == "__main__":
    unittest.main()
