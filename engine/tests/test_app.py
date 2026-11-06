"""Asset-free startup and configuration checks for the editor."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.request import urlopen

from app import Handler, Project, _patch_kaleido_binary_io
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

    def test_compiler_copy_is_safe_for_windows_binary_and_utf8_io(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kaleido = root / "kaleido"
            patch_checkout = root / "patch"
            repack = kaleido / "rom-repack"
            repack.mkdir(parents=True)
            patch_checkout.mkdir()
            files = {
                kaleido / "rom-repack/toolkit.rb": "content = File.read(entry_path)\n",
                kaleido / "rom-repack/scenario.rb": "File.write(file, data)\n",
                kaleido / "rom-repack/kal_tl.rb": "content_lines = File.read(e).lines\n",
                patch_checkout / "compile.rb": "require 'fileutils'\nkaleido_cmd = ['ruby', 'kal_tl.rb', debug_mode_str]\n",
            }
            for path, contents in files.items():
                path.write_text(contents, encoding="utf-8")
            _patch_kaleido_binary_io(kaleido, patch_checkout)
            _patch_kaleido_binary_io(kaleido, patch_checkout)
            self.assertIn("File.binread(entry_path)", (repack / "toolkit.rb").read_text(encoding="utf-8"))
            self.assertIn("File.binwrite(file, data)", (repack / "scenario.rb").read_text(encoding="utf-8"))
            self.assertIn("File.read(e, encoding: 'UTF-8')", (repack / "kal_tl.rb").read_text(encoding="utf-8"))
            compiler = (patch_checkout / "compile.rb").read_text(encoding="utf-8")
            self.assertEqual(compiler.count("require 'rbconfig'"), 1)
            self.assertIn("kaleido_cmd = [RbConfig.ruby, 'kal_tl.rb',", compiler)

    def test_config_relative_font_and_appdata_install(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = Project.__new__(Project)
            project.config_path = root / "config.local.json"
            project.config = {
                "arabic_font_path": "fonts/NotoSansArabic.ttf",
                "suyu_load_dir": "%APPDATA%/suyu/load",
                "title_id": "0100451020714000",
            }
            project.root = root / "project"
            project.lock = threading.RLock()
            patch_file = project.root / "build" / "patch.rom"
            patch_file.parent.mkdir(parents=True)
            patch_file.write_bytes(b"ROM2" + bytes(64))
            self.assertEqual(project.arabic_font_path(), root / "fonts" / "NotoSansArabic.ttf")
            with patch.dict(os.environ, {"APPDATA": str(root / "App Data")}):
                installed = project.install()
            target = root / "App Data" / "suyu" / "load" / "0100451020714000" / "Kaleido2-Arabic-Editor" / "romfs" / "patch.rom"
            self.assertEqual(Path(installed["path"]), target)
            self.assertEqual(target.read_bytes(), patch_file.read_bytes())

    def test_project_resolves_relative_config_paths_and_keeps_path_executables(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = root / "inputs"
            inputs.mkdir()
            (inputs / "dialogue.txt").write_text("00001\t@r仮文。\n", encoding="utf-8")
            (inputs / "main.rb").write_text("", encoding="utf-8")
            config = root / "config.local.json"
            config.write_text(json.dumps({
                "project_dir": "./project",
                "original_dialogue": "inputs/dialogue.txt",
                "original_script": "inputs/main.rb",
                "patch_source": "dependencies/kaleido2-patch",
                "kaleido_path": "dependencies/kaleido",
                "sdu_bin": "tools/sdu.exe",
                "enter_extractor_bin": "EnterExtractor.exe",
                "ruby_bin": "ruby.exe",
                "ruby_load_paths": ["dependencies/ruby/lib"],
                "suyu_load_dir": "%APPDATA%/suyu/load",
            }), encoding="utf-8")
            with patch.dict(os.environ, {"APPDATA": str(root / "App Data")}):
                project = Project(config)
            self.assertEqual(project.root, root / "project")
            self.assertEqual(project.config["patch_source"], str(root / "dependencies" / "kaleido2-patch"))
            self.assertEqual(project.config["kaleido_path"], str(root / "dependencies" / "kaleido"))
            self.assertEqual(project.config["sdu_bin"], str(root / "tools" / "sdu.exe"))
            self.assertEqual(project.config["enter_extractor_bin"], "EnterExtractor.exe")
            self.assertEqual(project.config["ruby_bin"], "ruby.exe")
            self.assertEqual(project.config["ruby_load_paths"], [str(root / "dependencies" / "ruby" / "lib")])
            self.assertEqual(project.config["suyu_load_dir"], str(root / "App Data" / "suyu" / "load"))


if __name__ == "__main__":
    unittest.main()
