import subprocess
import unittest
from unittest.mock import patch

import terminal_bg_rotator


class AppIsRunningTest(unittest.TestCase):
    @patch("terminal_bg_rotator.subprocess.run")
    def test_matches_process_name_case_insensitively(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=["ps", "-axo", "command="],
            returncode=0,
            stdout="/Applications/Ghostty.app/Contents/MacOS/ghostty\n",
        )

        self.assertTrue(terminal_bg_rotator.app_is_running("Ghostty"))


if __name__ == "__main__":
    unittest.main()
