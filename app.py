"""Local browser editor for a user's Kaleidoscope II translation project.

Only project files are served or written. Game assets and keys are never
embedded in this application; paths come from a local JSON configuration.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import shutil
import struct
import subprocess
import threading
from email import policy
from email.parser import BytesParser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from engine import TranslationError, export_patch
from engine.fnt6 import DEFAULT_ARABIC_FONT
from engine.images import (
    ImagePipelineError,
    export_images,
    import_images,
    load_image_manifest,
    preview_images,
)
from engine.script_strings import extract_script_strings, merge_script_strings


LINE = re.compile(r"^(\d+)\t(.*)$")
LEADING_COMMANDS = re.compile(r"^(?:(?:@v[^.]+\.|@z\d+\.|@s\d+\.|@a\d+\.))*")
VIDEO_NAMES = ("op2", "ed")
MAX_UPLOAD = 300 * 1024 * 1024
WINDOWS_ENV_REFERENCE = re.compile(r"%([A-Za-z_][A-Za-z0-9_]*)%")
CONFIG_PATH_KEYS = (
    "project_dir", "original_dialogue", "original_script", "original_story_font",
    "original_system_font", "arabic_font_path", "data_rom", "sdu_bin",
    "enter_extractor_bin", "patch_source", "kaleido_path", "ruby_bin",
    "suyu_load_dir",
)
EXECUTABLE_PATH_KEYS = frozenset(("sdu_bin", "enter_extractor_bin", "ruby_bin"))


def _read_json(path: Path, fallback: dict) -> dict:
    if not path.exists():
        return dict(fallback)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _safe_within(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ValueError("Path escapes the translation project")
    return candidate


def _config_path(config_path: Path, value: str | Path) -> Path:
    """Resolve a user path, including Windows environment variables, from the config file."""
    expanded = os.path.expandvars(os.path.expanduser(str(value)))

    def replace_variable(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in os.environ:
            raise ValueError(f"Environment variable %{name}% is not set")
        return os.environ[name]

    expanded = WINDOWS_ENV_REFERENCE.sub(replace_variable, expanded)
    path = Path(expanded)
    if not path.is_absolute():
        path = config_path.parent / path
    return path.resolve()


def _png_dimensions(data: bytes) -> tuple[int, int]:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError("Upload must be a PNG")
    return struct.unpack(">II", data[16:24])


def _patch_kaleido_binary_io(kaleido_copy: Path, patch_copy: Path) -> None:
    """Make a disposable compiler copy use binary I/O and UTF-8 on Windows.

    Kaleido's original text-mode reads can change CRLF and treat 0x1A as EOF
    when it packs FNT6, PIC, TXA, or MP4 files. Its dialogue reader uses the
    machine's default encoding, which can corrupt Japanese or Arabic text.
    Never alter the user's checkout.
    """
    replacements = (
        (kaleido_copy / "rom-repack/toolkit.rb", "File.read(entry_path)", "File.binread(entry_path)"),
        (kaleido_copy / "rom-repack/scenario.rb", "File.write(file, data)", "File.binwrite(file, data)"),
        (kaleido_copy / "rom-repack/kal_tl.rb", "File.read(e).lines", "File.read(e, encoding: 'UTF-8').lines"),
        (patch_copy / "compile.rb", "require 'fileutils'", "require 'fileutils'\nrequire 'rbconfig'"),
        (patch_copy / "compile.rb", "kaleido_cmd = ['ruby', 'kal_tl.rb',", "kaleido_cmd = [RbConfig.ruby, 'kal_tl.rb',"),
    )
    for path, old, new in replacements:
        source = path.read_text(encoding="utf-8")
        if new in source:
            continue
        if source.count(old) != 1:
            raise RuntimeError(f"Unsupported Kaleido checkout: expected {old} in {path}")
        path.write_text(source.replace(old, new), encoding="utf-8")


class Project:
    def __init__(self, config_path: Path):
        self.config_path = config_path.resolve()
        self.config = _read_json(self.config_path, {})
        for key in CONFIG_PATH_KEYS:
            value = self.config.get(key)
            if not value:
                continue
            if key in EXECUTABLE_PATH_KEYS and not any(sep in str(value) for sep in ("/", "\\", "%", "~", "$")):
                continue  # A bare executable name should still be looked up on PATH.
            self.config[key] = str(_config_path(self.config_path, value))
        if self.config.get("ruby_load_paths"):
            self.config["ruby_load_paths"] = [
                str(_config_path(self.config_path, value)) for value in self.config["ruby_load_paths"]
            ]
        self.root = Path(self.config["project_dir"])
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.original_dialogue = Path(self.config["original_dialogue"]).read_text(encoding="utf-8")
        self.original_script = Path(self.config["original_script"]).read_text(encoding="utf-8")
        self.catalog = extract_script_strings(self.original_script)
        self.catalog_by_id = {row.id: row for row in self.catalog}
        self.entries = self._parse_dialogue(self.original_dialogue)
        self.entries_by_id = {row["id"]: row for row in self.entries}
        self.name_counts: dict[str, int] = {}
        for row in self.entries:
            if row["speaker"]:
                self.name_counts[row["speaker"]] = self.name_counts.get(row["speaker"], 0) + 1
        self.edits = _read_json(self.root / "dialogue_edits.json", {})
        self.names = _read_json(self.root / "name_edits.json", {})
        self.strings = _read_json(self.root / "string_edits.json", {})
        self.last_export = _read_json(self.root / "last_export.json", {})

    @staticmethod
    def _parse_dialogue(text: str) -> list[dict]:
        rows: list[dict] = []
        section = ""
        for line in text.splitlines():
            if line.startswith("#"):
                section = line.lstrip("# ").strip()
                continue
            match = LINE.match(line)
            if not match:
                continue
            line_id, message = match.groups()
            if "@r" not in message:
                raise ValueError(f"Dialogue {line_id} lacks speaker separator")
            speaker, remainder = message.split("@r", 1)
            prefix = LEADING_COMMANDS.match(remainder).group()
            content = remainder[len(prefix) :]
            voice = re.search(r"@v([^.]+)\.", prefix)
            rows.append({
                "id": line_id, "speaker": speaker, "prefix": prefix,
                "source": content, "voice": voice.group(1) if voice else "",
                "section": section,
            })
        if len(rows) != len({row["id"] for row in rows}):
            raise ValueError("Duplicate IDs in original dialogue")
        # Put the playable story before six high-numbered debug/test entries.
        rows.sort(key=lambda row: (int(row["id"]) > 5926, int(row["id"])))
        return rows

    def status(self) -> dict:
        with self.lock:
            image_rows = preview_images(self.root)
            video_rows = self.videos()
            return {
                "dialogue": {"total": len(self.entries), "translated": len(self.edits)},
                "names": {"total": len(self.name_counts), "translated": len(self.names)},
                "strings": {
                    "total": sum(row.editable for row in self.catalog),
                    "translated": len(self.strings),
                    "locked": sum(not row.editable for row in self.catalog),
                },
                "images": {"total": len(image_rows), "modified": sum(row["modified"] for row in image_rows)},
                "videos": {"total": len(video_rows), "modified": sum(row["modified"] for row in video_rows)},
                "ready": all(Path(self.config[key]).is_file() for key in (
                    "original_dialogue", "original_script", "original_story_font", "original_system_font", "data_rom"
                )) and self.arabic_font_path().is_file(),
                "last_export": self.last_export,
            }

    def arabic_font_path(self) -> Path:
        configured = self.config.get("arabic_font_path")
        if not configured:
            return DEFAULT_ARABIC_FONT.resolve()
        return _config_path(self.config_path, configured)

    def suyu_load_dir(self) -> Path:
        return _config_path(self.config_path, self.config.get("suyu_load_dir") or "%APPDATA%/suyu/load")

    def dialogue_page(self, q: str, offset: int, limit: int, filter_name: str) -> dict:
        q = q.casefold().strip()
        with self.lock:
            rows = self.entries
            if filter_name == "translated":
                rows = [row for row in rows if row["id"] in self.edits]
            elif filter_name == "untranslated":
                rows = [row for row in rows if row["id"] not in self.edits]
            if q:
                rows = [row for row in rows if q in (
                    row["id"] + " " + row["speaker"] + " " + row["source"] + " " +
                    self.edits.get(row["id"], "") + " " + row["section"]
                ).casefold()]
            total = len(rows)
            items = [{**row, "translation": self.edits.get(row["id"], "")} for row in rows[offset : offset + limit]]
            return {"items": items, "total": total, "offset": offset, "limit": limit}

    def save_dialogue(self, line_id: str, translation: str) -> dict:
        if line_id not in self.entries_by_id:
            raise KeyError("Unknown dialogue ID")
        if not isinstance(translation, str):
            raise ValueError("Translation must be text")
        translation = translation.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "@r").strip()
        if "\t" in translation or "\x00" in translation:
            raise ValueError("Tabs and NUL characters are not allowed in dialogue")
        with self.lock:
            if translation:
                self.edits[line_id] = translation
            else:
                self.edits.pop(line_id, None)
            _atomic_json(self.root / "dialogue_edits.json", self.edits)
        return {"id": line_id, "translation": translation}

    def names_page(self) -> dict:
        with self.lock:
            return {"items": [
                {"source": name, "translation": self.names.get(name, ""), "count": count}
                for name, count in sorted(self.name_counts.items(), key=lambda pair: (-pair[1], pair[0]))
            ]}

    def save_name(self, source: str, translation: str) -> dict:
        if source not in self.name_counts:
            raise KeyError("Unknown speaker name")
        if not isinstance(translation, str):
            raise ValueError("Translation must be text")
        translation = translation.strip()
        if any(char in translation for char in ("\t", "\n", "\r", "@", "\x00")):
            raise ValueError("Speaker names cannot contain controls or @ tags")
        with self.lock:
            if translation:
                self.names[source] = translation
            else:
                self.names.pop(source, None)
            _atomic_json(self.root / "name_edits.json", self.names)
        return {"source": source, "translation": translation}

    def strings_page(self) -> dict:
        with self.lock:
            return {"items": [
                {"id": row.id, "source": row.source, "translation": self.strings.get(row.id, ""),
                 "kind": row.kind, "context": row.context, "editable": row.editable}
                for row in self.catalog
            ]}

    def save_string(self, string_id: str, translation: str) -> dict:
        row = self.catalog_by_id.get(string_id)
        if row is None:
            raise KeyError("Unknown interface string")
        if not row.editable:
            raise ValueError("This gallery asset key cannot be translated independently")
        if not isinstance(translation, str):
            raise ValueError("Translation must be text")
        translation = translation.strip()
        if not translation:
            with self.lock:
                self.strings.pop(string_id, None)
                _atomic_json(self.root / "string_edits.json", self.strings)
            return {"id": string_id, "translation": ""}
        # Validate with the game-specific safe merger before saving.
        merge_script_strings(self.original_script, {string_id: translation}, expected_sources={string_id: row.source})
        with self.lock:
            self.strings[string_id] = translation
            _atomic_json(self.root / "string_edits.json", self.strings)
        return {"id": string_id, "translation": translation}

    def image_page(self, q: str, offset: int, limit: int) -> dict:
        with self.lock:
            rows = preview_images(self.root)
        q = q.casefold().strip()
        if q:
            rows = [row for row in rows if q in (row["relative_path"] + " " + row["rom_path"]).casefold()]
        return {"items": [
            {"path": row["relative_path"], "rom_path": row["rom_path"],
             "width": row["width"], "height": row["height"], "modified": row["modified"]}
            for row in rows[offset : offset + limit]
        ], "total": len(rows), "offset": offset, "limit": limit}

    def image_file(self, relative: str) -> Path:
        manifest = load_image_manifest(self.root)
        allowed = {image["path"] for asset in manifest["assets"].values() for image in asset["images"]}
        if relative not in allowed:
            raise KeyError("Unknown image")
        path = _safe_within(self.root / "images", relative)
        if not path.is_file():
            raise KeyError("Image is missing")
        return path

    def save_image(self, relative: str, data: bytes) -> dict:
        path = self.image_file(relative)
        manifest = load_image_manifest(self.root)
        record = next(image for asset in manifest["assets"].values() for image in asset["images"] if image["path"] == relative)
        if _png_dimensions(data) != (record["width"], record["height"]):
            raise ValueError(f"PNG must remain {record['width']}×{record['height']} pixels")
        with self.lock:
            temporary = path.with_name(path.name + ".tmp")
            temporary.write_bytes(data)
            os.replace(temporary, path)
        return {"path": relative, "modified": True}

    def extract_images(self, include_pictures: bool) -> dict:
        with self.lock:
            manifest = export_images(
                self.config["data_rom"], self.root, self.config["sdu_bin"],
                self.config["enter_extractor_bin"], include_pictures=include_pictures,
            )
        return {"archives": len(manifest["assets"]), "previews": len(preview_images(self.root))}

    def videos(self) -> list[dict]:
        root = self.root / "videos"
        return [{"name": name, "path": f"movie/{name}.mp4", "modified": (root / f"{name}.mp4").is_file()}
                for name in VIDEO_NAMES]

    def video_file(self, name: str) -> Path:
        if name not in VIDEO_NAMES:
            raise KeyError("Unknown game video")
        replacement = self.root / "videos" / f"{name}.mp4"
        if replacement.is_file():
            return replacement
        original = self.root / "videos" / "original" / f"{name}.mp4"
        if not original.is_file():
            original.parent.mkdir(parents=True, exist_ok=True)
            process = subprocess.run(
                [self.config["sdu_bin"], "rom", "extract-one", self.config["data_rom"],
                 f"/movie/{name}.mp4", str(original)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
            )
            if process.returncode or not original.is_file():
                raise RuntimeError("Could not extract original game video: " + process.stderr[-300:])
        return original

    def save_video(self, name: str, data: bytes) -> dict:
        if name not in VIDEO_NAMES:
            raise KeyError("Unknown game video")
        if len(data) < 16 or b"ftyp" not in data[4:16]:
            raise ValueError("Upload must be an MP4 file")
        root = self.root / "videos"
        root.mkdir(exist_ok=True)
        path = root / f"{name}.mp4"
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)
        return {"name": name, "modified": True}

    def _edited_dialogue(self) -> str:
        lines = []
        for row in self.entries:
            line_id = row["id"]
            if line_id not in self.edits and row["speaker"] not in self.names:
                continue
            speaker = self.names.get(row["speaker"], row["speaker"])
            body = self.edits.get(line_id, row["source"])
            lines.append(f"{line_id}\t{speaker}@r{row['prefix']}{body}")
        return "\n".join(lines) + ("\n" if lines else "")

    def export(self) -> dict:
        with self.lock:
            build_root = self.root / "build"
            workspace = build_root / "workspace"
            if workspace.exists():
                shutil.rmtree(workspace)
            patch = workspace / "kaleido2-patch"
            source = Path(self.config["patch_source"]).resolve()
            shutil.copytree(source, patch, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            # Copying this small compiler checkout avoids Windows symlink
            # privileges and keeps each build independent of later edits.
            kaleido_copy = workspace / "kaleido"
            shutil.copytree(
                Path(self.config["kaleido_path"]).resolve(), kaleido_copy,
                ignore=shutil.ignore_patterns(".git", "__pycache__"),
            )
            _patch_kaleido_binary_io(kaleido_copy, patch)
            (workspace / "output").mkdir(parents=True)
            edits_path = workspace / "edited-dialogue.txt"
            edits_path.write_text(self._edited_dialogue(), encoding="utf-8")
            ui_path = workspace / "ui-edits.json"
            ui_path.write_text(json.dumps(self.strings, ensure_ascii=False), encoding="utf-8")
            generated = workspace / "generated"
            result = export_patch(
                edits_path, self.config["original_dialogue"],
                self.config["original_story_font"], self.config["original_system_font"],
                generated, ui_strings_path=ui_path,
                arabic_font_path=self.arabic_font_path(),
            )
            shutil.copy2(result.dialogue_path, patch / "dialogue.txt")
            shutil.copy2(result.story_font_path, patch / "rom_source" / "newrodin-medium.fnt")
            shutil.copy2(result.system_font_path, patch / "rom_source" / "system.fnt")
            converted_ui = json.loads(result.ui_strings_path.read_text(encoding="utf-8")) if result.ui_strings_path else {}
            merged_script = merge_script_strings(
                self.original_script, converted_ui,
                expected_sources={row.id: row.source for row in self.catalog},
            )
            (patch / "base" / "main.rb").write_text(merged_script, encoding="utf-8")
            if load_image_manifest(self.root)["assets"]:
                import_images(self.root, patch / "rom_source", self.config["enter_extractor_bin"])
            for name in VIDEO_NAMES:
                video = self.root / "videos" / f"{name}.mp4"
                if video.exists():
                    destination = patch / "rom_source" / "movie" / f"{name}.mp4"
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(video, destination)
            env = os.environ.copy()
            # Keep a configured Ruby installation available to child processes.
            ruby_bin = self.config["ruby_bin"]
            if any(sep in ruby_bin for sep in ("/", "\\")):
                env["PATH"] = str(Path(ruby_bin).parent) + os.pathsep + env.get("PATH", "")
            if self.config.get("ruby_load_paths"):
                env["RUBYLIB"] = os.pathsep.join(self.config["ruby_load_paths"])
            patch_output = workspace / "output" / "patch.rom"
            process = subprocess.run(
                [self.config["ruby_bin"], "compile.rb", str(patch_output), "skip-images"],
                cwd=patch, env=env, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=600,
            )
            log = (process.stdout + "\n" + process.stderr)[-12000:]
            (build_root / "build.log").write_text(log, encoding="utf-8")
            if process.returncode or not patch_output.is_file():
                raise RuntimeError("Game patch compiler failed; see build/build.log: " + log[-900:])
            final_patch = build_root / "patch.rom"
            shutil.copy2(patch_output, final_patch.with_suffix(".rom.tmp"))
            os.replace(final_patch.with_suffix(".rom.tmp"), final_patch)
            self.last_export = {
                "path": str(final_patch), "bytes": final_patch.stat().st_size,
                "dialogue_translated": len(self.edits), "names_translated": len(self.names),
                "strings_translated": len(self.strings),
                "images_modified": sum(row["modified"] for row in preview_images(self.root)),
                "videos_modified": sum(row["modified"] for row in self.videos()),
                "font_tokens": result.report["unique_glyph_tokens"],
            }
            _atomic_json(self.root / "last_export.json", self.last_export)
            return self.last_export

    def install(self) -> dict:
        with self.lock:
            patch = self.root / "build" / "patch.rom"
            if not patch.is_file():
                raise ValueError("Export a patch before installing")
            title_root = self.suyu_load_dir() / self.config["title_id"]
            mod_name = self.config.get("mod_name", "Kaleido2-Arabic-Editor")
            destination = title_root / mod_name / "romfs" / "patch.rom"
            conflicts = sorted(str(path.parent.parent.name) for path in title_root.glob("*/romfs/patch.rom") if path != destination)
            if conflicts:
                raise ValueError("Other patch.rom mods are installed for this game: " + ", ".join(conflicts))
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name("patch.rom.tmp")
            shutil.copy2(patch, temporary)
            os.replace(temporary, destination)
            return {"path": str(destination), "bytes": destination.stat().st_size, "restart_required": True}


class Handler(BaseHTTPRequestHandler):
    project: Project
    static_root: Path

    def _json(self, value: object, status: int = 200) -> None:
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _file(self, path: Path, content_type: str | None = None) -> None:
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _video_file(self, path: Path) -> None:
        size = path.stat().st_size
        requested = self.headers.get("Range", "")
        start, end = 0, size - 1
        partial = False
        if requested:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested.strip())
            if not match or (not match.group(1) and not match.group(2)):
                raise ValueError("Unsupported video range")
            if match.group(1):
                start = int(match.group(1))
                end = min(size - 1, int(match.group(2))) if match.group(2) else size - 1
            else:
                start = max(0, size - int(match.group(2)))
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            partial = True
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = end - start + 1
            while remaining:
                chunk = handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > MAX_UPLOAD:
            raise ValueError("Upload is too large")
        return self.rfile.read(length)

    def _multipart(self) -> dict[str, bytes]:
        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("multipart/form-data;"):
            raise ValueError("Expected multipart form data")
        envelope = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + self._body()
        message = BytesParser(policy=policy.default).parsebytes(envelope)
        result = {}
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if name:
                result[name] = part.get_payload(decode=True)
        return result

    def do_GET(self) -> None:
        try:
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            route = parsed.path
            one = lambda key, default="": query.get(key, [default])[0]
            if route == "/api/status":
                self._json(self.project.status())
            elif route == "/api/dialogue":
                self._json(self.project.dialogue_page(one("q"), max(0, int(one("offset", "0"))), min(100, max(1, int(one("limit", "50")))), one("filter")))
            elif route == "/api/names":
                self._json(self.project.names_page())
            elif route == "/api/strings":
                self._json(self.project.strings_page())
            elif route == "/api/images":
                self._json(self.project.image_page(one("q"), max(0, int(one("offset", "0"))), min(100, max(1, int(one("limit", "60"))))))
            elif route == "/api/image":
                self._file(self.project.image_file(one("path")), "image/png")
            elif route == "/api/videos":
                self._json({"items": self.project.videos()})
            elif route == "/api/video":
                self._video_file(self.project.video_file(one("name")))
            else:
                target = "index.html" if route == "/" else route.lstrip("/")
                path = _safe_within(self.static_root, target)
                if not path.is_file():
                    raise KeyError("Not found")
                self._file(path)
        except (KeyError, FileNotFoundError) as error:
            self._json({"error": str(error)}, 404)
        except (ValueError, TranslationError, ImagePipelineError) as error:
            self._json({"error": str(error)}, 400)
        except Exception as error:
            self._json({"error": str(error)}, 500)

    def do_POST(self) -> None:
        try:
            route = urlsplit(self.path).path
            if route in ("/api/images/upload", "/api/videos/upload"):
                form = self._multipart()
                if route == "/api/images/upload":
                    self._json(self.project.save_image(form["path"].decode("utf-8"), form["file"]))
                else:
                    self._json(self.project.save_video(form["name"].decode("utf-8"), form["file"]))
                return
            payload = json.loads(self._body() or b"{}")
            if not isinstance(payload, dict):
                raise ValueError("Expected JSON object")
            if route.startswith("/api/dialogue/"):
                self._json(self.project.save_dialogue(unquote(route.removeprefix("/api/dialogue/")), payload.get("translation")))
            elif route.startswith("/api/names/"):
                self._json(self.project.save_name(unquote(route.removeprefix("/api/names/")), payload.get("translation")))
            elif route.startswith("/api/strings/"):
                self._json(self.project.save_string(unquote(route.removeprefix("/api/strings/")), payload.get("translation")))
            elif route == "/api/images/extract":
                self._json(self.project.extract_images(bool(payload.get("all", False))))
            elif route == "/api/export":
                self._json(self.project.export())
            elif route == "/api/install":
                self._json(self.project.install())
            else:
                raise KeyError("Not found")
        except (KeyError, FileNotFoundError) as error:
            self._json({"error": str(error)}, 404)
        except (ValueError, TranslationError, ImagePipelineError) as error:
            self._json({"error": str(error)}, 400)
        except Exception as error:
            self._json({"error": str(error)}, 500)


def main() -> None:
    parser = argparse.ArgumentParser(description="Kaleidoscope II Arabic translation editor")
    parser.add_argument("--config", type=Path, required=True, help="local game/project path configuration")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    project = Project(args.config)
    handler = type("ProjectHandler", (Handler,), {"project": project, "static_root": Path(__file__).resolve().parent / "static"})
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Arabic editor: http://{args.host}:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
