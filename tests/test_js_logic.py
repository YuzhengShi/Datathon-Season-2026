"""The web app's logic is plain JavaScript with its own tests; they run here too when Node.js is available."""

import glob
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def node_major() -> int:
    try:
        out = (
            subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=20).stdout.strip().lstrip("v")
        )
        return int(out.split(".")[0])
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


class JavaScriptLogicTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node") and node_major() >= 20, "Node.js 20 or newer is not installed")
    def test_the_web_app_logic_passes_its_own_tests(self):
        files = sorted(glob.glob(str(ROOT / "tests" / "js" / "*.test.mjs")))
        self.assertTrue(files, "no JavaScript tests found")
        done = subprocess.run(["node", "--test", *files], cwd=ROOT, capture_output=True, text=True, timeout=180)
        self.assertEqual(done.returncode, 0, (done.stdout + done.stderr)[-3000:])


if __name__ == "__main__":
    unittest.main()
