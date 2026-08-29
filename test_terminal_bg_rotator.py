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


class ChooseImageTest(unittest.TestCase):
    @patch("terminal_bg_rotator.load_state")
    def test_follows_previous_image_id_when_album_order_changes(self, load_state):
        load_state.return_value = {"index": 0, "image_id": "second"}
        images = [{"id": "first"}, {"id": "second"}, {"id": "third"}]

        index, image = terminal_bg_rotator.choose_image(images, randomize=False)

        self.assertEqual(index, 2)
        self.assertEqual(image["id"], "third")

    @patch("terminal_bg_rotator.load_state")
    def test_random_selection_is_not_used_by_default(self, load_state):
        load_state.return_value = {"index": 0, "image_id": "first"}
        images = [{"id": "first"}, {"id": "second"}, {"id": "third"}]

        index, image = terminal_bg_rotator.choose_image(images, randomize=False)

        self.assertEqual(index, 1)
        self.assertEqual(image["id"], "second")


class LoadImagesTest(unittest.TestCase):
    @patch("terminal_bg_rotator.sync_manifest")
    def test_refreshes_manifest_from_a_different_album(self, sync_manifest):
        with tempfile.TemporaryDirectory() as directory:
            manifest_file = Path(directory) / "manifest.json"
            manifest_file.write_text(
                '{"album_url": "https://imgur.com/a/other", '
                '"images": [{"id": "ghostty-e2e-b"}]}',
                encoding="utf-8",
            )
            sync_manifest.return_value = [{"id": "one-piece"}]
            with patch("terminal_bg_rotator.MANIFEST_FILE", manifest_file):
                images = terminal_bg_rotator.load_images("https://imgur.com/a/jsstNId")

        sync_manifest.assert_called_once_with("https://imgur.com/a/jsstNId")
        self.assertEqual(images, [{"id": "one-piece"}])


if __name__ == "__main__":
    unittest.main()
