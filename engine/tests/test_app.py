"""Asset-free startup check for the local editor on Linux and Windows."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

from app import Handler, Project
from engine.fnt6 import DEFAULT_ARABIC_FONT


class EditorStartupTests(unittest.TestCase):
    def test_editor_serves_project_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_files = {
                "original_dialogue": ("dialogue.txt", "00001\t@r仮文甲。\n"),
                "original_script": ("main.rb", ""),
                "original_story_font": ("story.fnt", "synthetic font fixture"),
                "original_system_font": ("system.fnt", "synthetic font fixture"),
                "data_rom": ("data.rom", "synthetic archive fixture"),
            }
            config: dict[str, str] = {"project_dir": str(root / "project"),
                                      "arabic_font_path": str(DEFAULT_ARABIC_FONT)}
            for key, (name, content) in source_files.items():
                path = root / name
                path.write_text(content, encoding="utf-8")
                config[key] = str(path)
            config_path = root / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")

            project = Project(config_path)
            handler = type("TestHandler", (Handler,), {"project": project,
                           "static_root": Path(__file__).resolve().parents[2] / "static"})
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urlopen(f"http://127.0.0.1:{server.server_port}/api/status", timeout=5) as response:
                    status = json.load(response)
                self.assertEqual(status["dialogue"]["total"], 1)
                self.assertTrue(status["ready"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
