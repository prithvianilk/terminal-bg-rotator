import subprocess
import tempfile
import unittest
from pathlib import Path
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


class UpdateGhosttyTest(unittest.TestCase):
    @patch("terminal_bg_rotator.app_is_running", return_value=False)
    def test_uses_cached_image_and_collapses_managed_blocks(self, _app_is_running):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.ghostty"
            managed_block = (
                "# terminal-bg-rotator:start\n"
                'background-image = "/old/active.png"\n'
                "# terminal-bg-rotator:end\n"
            )
            config.write_text(
                f"font-size = 14\n\n{managed_block}\n{managed_block}",
                encoding="utf-8",
            )
            cached_image = Path(directory) / "cache" / "new.png"

            with patch("terminal_bg_rotator.ghostty_config_path", return_value=config):
                terminal_bg_rotator.update_ghostty("0.1", cached_image)

            updated = config.read_text(encoding="utf-8")
            self.assertEqual(updated.count("# terminal-bg-rotator:start"), 1)
            self.assertIn(f'background-image = "{cached_image}"', updated)
            self.assertIn("font-size = 14", updated)


if __name__ == "__main__":
    unittest.main()
