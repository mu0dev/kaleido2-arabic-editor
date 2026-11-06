"""Export editable game images and rebuild changed PIC/TXA overrides.

The project directory holds user-owned working copies of decoded PNGs. This
module never bundles game artwork; it reads a local ``data.rom`` supplied by
the user and produces only the changed image containers for a patch build.

Requires ``sdu`` from AuroraWright/shin and ``EnterExtractor`` from
DCNick3/EnterExtractor. Neither command is invoked through a shell.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import struct
import subprocess
import sys
import tempfile
from typing import Any, Iterable


MANIFEST_VERSION = 1
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class ImagePipelineError(RuntimeError):
    """A game image could not be exported or rebuilt safely."""


def _binary(path: str | Path) -> str:
    result = shutil.which(str(path))
    if result is None:
        raise ImagePipelineError(f"Executable not found: {path}")
    return result


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        process = subprocess.run(
            args, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
        )
    except OSError as exc:
        raise ImagePipelineError(f"Could not run {args[0]}: {exc}") from exc
    if process.returncode:
        detail = (process.stderr or process.stdout).strip()
        raise ImagePipelineError(f"{' '.join(args[:2])} failed ({process.returncode}): {detail}")
    return process


def _rom_relative(name: str) -> str:
    """Normalize a ROM entry to a safe path relative to the archive root."""
    clean = name.lstrip("/")
    path = PurePosixPath(clean)
    if not clean or path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ImagePipelineError(f"Invalid ROM asset path: {name!r}")
    return path.as_posix()


def _manifest_file(root: Path, name: str) -> Path:
    """Resolve a manifest path without permitting reads outside its project."""
    relative = PurePosixPath(name)
    if relative.is_absolute() or any(part in ("", ".", "..") for part in relative.parts):
        raise ImagePipelineError(f"Unsafe image manifest path: {name!r}")
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ImagePipelineError(f"Image manifest path escapes project: {name!r}")
    return resolved


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) < 24 or header[:8] != PNG_SIGNATURE or header[12:16] != b"IHDR":
        raise ImagePipelineError(f"Not a valid PNG: {path}")
    width, height = struct.unpack(">II", header[16:24])
    if not width or not height:
        raise ImagePipelineError(f"Invalid PNG dimensions: {path}")
    return width, height


def _txa_flags(path: Path) -> int:
    with path.open("rb") as handle:
        header = handle.read(16)
    if len(header) < 16 or header[:4] != b"TXA4":
        raise ImagePipelineError(f"Not a TXA4 archive: {path}")
    return struct.unpack_from("<I", header, 12)[0]


def _txa_for_extractor(raw: Path, normalized: Path) -> Path:
    """Adapt Gerokasu2 TXA flags for EnterExtractor's old boolean decoder.

    The current game uses bit 0 of the field at offset 12 to select dictionary
    encoding. EnterExtractor treats any nonzero word as true and crashes on
    ``title.txa`` (value 2). Its conversion should see only bit 0; other bits
    are restored on repacked output.
    """
    flags = _txa_flags(raw)
    if flags in (0, 1):
        return raw
    data = bytearray(raw.read_bytes())
    struct.pack_into("<I", data, 12, flags & 1)
    normalized.parent.mkdir(parents=True, exist_ok=True)
    normalized.write_bytes(data)
    return normalized


def _restore_txa_flags(repacked: Path, original: Path) -> None:
    original_flags = _txa_flags(original)
    data = bytearray(repacked.read_bytes())
    flags = _txa_flags(repacked)
    struct.pack_into("<I", data, 12, (original_flags & ~1) | (flags & 1))
    repacked.write_bytes(data)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _images_dir(project_dir: str | Path) -> Path:
    return Path(project_dir).expanduser().resolve() / "images"


def load_image_manifest(project_dir: str | Path) -> dict[str, Any]:
    """Load a project's image manifest; return an empty one before export."""
    path = _images_dir(project_dir) / "manifest.json"
    if not path.exists():
        return {"version": MANIFEST_VERSION, "rom_path": None, "assets": {}}
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("version") != MANIFEST_VERSION or not isinstance(manifest.get("assets"), dict):
        raise ImagePipelineError(f"Unsupported image manifest: {path}")
    return manifest


def list_image_assets(data_rom: str | Path, sdu_bin: str | Path = "sdu") -> list[dict[str, str]]:
    """List patchable PIC/TXA files in a local game archive.

    A TXA is a multi-texture UI atlas. A PIC is a standalone background, card,
    CG, or cut-in. BUP character art and MSK masks are intentionally excluded:
    EnterExtractor can decode them, but its ``-replace`` mode cannot rebuild
    them.
    """
    rom = Path(data_rom).expanduser().resolve()
    if not rom.is_file():
        raise ImagePipelineError(f"data.rom not found: {rom}")
    result = _run([_binary(sdu_bin), "rom", "list", str(rom)])
    assets = []
    for line in result.stdout.splitlines():
        if not line.startswith("FILE /"):
            continue
        relative = _rom_relative(line.removeprefix("FILE /"))
        suffix = PurePosixPath(relative).suffix.lower()
        if suffix not in (".pic", ".txa"):
            continue
        assets.append({"rom_path": relative, "kind": suffix[1:], "group": "menu" if suffix == ".txa" else "picture"})
    return sorted(assets, key=lambda item: item["rom_path"])


def export_images(
    data_rom: str | Path,
    project_dir: str | Path,
    sdu_bin: str | Path = "sdu",
    extractor_bin: str | Path = "EnterExtractor",
    *,
    selected: Iterable[str] | None = None,
    include_pictures: bool = False,
) -> dict[str, Any]:
    """Export menu atlases, selected images, or all patchable images as PNGs.

    ``selected`` contains archive-relative paths such as ``config.txa`` or
    ``picture/card/カード裏面.pic``. Without it, all 14 menu TXAs are exported;
    ``include_pictures=True`` adds the PICs. Repeated calls add new assets and
    preserve already exported PNG edits.

    Returns the manifest; ``preview_images`` provides individual PNG paths.
    """
    rom = Path(data_rom).expanduser().resolve()
    project = Path(project_dir).expanduser().resolve()
    image_root = _images_dir(project)
    manifest = load_image_manifest(project)
    if manifest["rom_path"] and manifest["rom_path"] != str(rom):
        raise ImagePipelineError("This image project already belongs to a different data.rom")
    manifest["rom_path"] = str(rom)

    available = {item["rom_path"]: item for item in list_image_assets(rom, sdu_bin)}
    if selected is not None:
        names = sorted({_rom_relative(item) for item in selected})
        unknown = sorted(set(names) - set(available))
        if unknown:
            raise ImagePipelineError(f"Not a patchable image in this ROM: {', '.join(unknown)}")
    else:
        names = [name for name, item in available.items() if item["kind"] == "txa" or include_pictures]

    sdu = _binary(sdu_bin)
    extractor = _binary(extractor_bin)
    image_root.mkdir(parents=True, exist_ok=True)
    for name in names:
        if name in manifest["assets"]:
            continue
        asset = available[name]
        raw = image_root / "raw" / name
        raw.parent.mkdir(parents=True, exist_ok=True)
        _run([sdu, "rom", "extract-one", str(rom), "/" + name, str(raw)])
        if asset["kind"] == "pic":
            png = image_root / "editable" / "pic" / PurePosixPath(name).with_suffix(".png")
            png.parent.mkdir(parents=True, exist_ok=True)
            _run([extractor, str(raw), str(png)])
            pngs = [png]
        else:
            rel = PurePosixPath(name)
            directory = image_root / "editable" / "txa" / rel.with_suffix("")
            directory.mkdir(parents=True, exist_ok=True)
            before = set(directory.glob("*.png"))
            with tempfile.TemporaryDirectory(prefix="txa-decode-", dir=image_root) as temporary:
                adapted = _txa_for_extractor(raw, Path(temporary) / "normalized.txa")
                _run([extractor, str(adapted), str(directory / (rel.stem + ".png"))])
            pngs = sorted(set(directory.glob("*.png")) - before)
            if not pngs:
                raise ImagePipelineError(f"No PNG textures decoded from {name}")
        manifest["assets"][name] = {
            "kind": asset["kind"],
            "raw_sha256": _hash(raw),
            "images": [
                {
                    "path": png.relative_to(image_root).as_posix(),
                    "sha256": _hash(png),
                    "width": _png_size(png)[0],
                    "height": _png_size(png)[1],
                }
                for png in pngs
            ],
        }
        _write_json(image_root / "manifest.json", manifest)
    return manifest


def preview_images(project_dir: str | Path) -> list[dict[str, Any]]:
    """Return local PNG paths and metadata for an image editor/gallery."""
    image_root = _images_dir(project_dir)
    manifest = load_image_manifest(project_dir)
    previews = []
    for name, asset in sorted(manifest["assets"].items()):
        name = _rom_relative(name)
        for image in asset["images"]:
            path = _manifest_file(image_root, image["path"])
            previews.append({
                "rom_path": name,
                "kind": asset["kind"],
                "path": str(path),
                "relative_path": image["path"],
                "width": image["width"],
                "height": image["height"],
                "modified": path.is_file() and _hash(path) != image["sha256"],
            })
    return previews


def import_images(
    project_dir: str | Path,
    patch_root: str | Path,
    extractor_bin: str | Path = "EnterExtractor",
) -> dict[str, Any]:
    """Rebuild only modified PNGs as PIC/TXA files under ``patch_root``.

    The output paths match the originals inside data.rom, ready for the
    scenario/ROM repacker's ``rom_source`` tree. Reverting a PNG to its exported
    bytes removes an override previously produced by this module. The caller
    should use a dedicated patch_root for image assets.
    """
    project = Path(project_dir).expanduser().resolve()
    image_root = _images_dir(project)
    destination = Path(patch_root).expanduser().resolve()
    manifest = load_image_manifest(project)
    if not manifest["assets"]:
        raise ImagePipelineError("No exported images; run export first")
    extractor = _binary(extractor_bin)
    changed: dict[str, list[Path]] = {}
    for untrusted_name, asset in manifest["assets"].items():
        name = _rom_relative(untrusted_name)
        raw = image_root / "raw" / name
        if not raw.is_file() or _hash(raw) != asset["raw_sha256"]:
            raise ImagePipelineError(f"Original image container changed or is missing: {raw}")
        edited = []
        for image in asset["images"]:
            png = _manifest_file(image_root, image["path"])
            if not png.is_file():
                raise ImagePipelineError(f"Editable PNG is missing: {png}")
            if _png_size(png) != (image["width"], image["height"]):
                raise ImagePipelineError(f"PNG dimensions changed; restore {image['width']}×{image['height']}: {png}")
            if _hash(png) != image["sha256"]:
                edited.append(png)
        if edited:
            changed[name] = edited

    state_path = image_root / "import-state.json"
    prior = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"patch_root": str(destination), "files": []}
    if prior.get("patch_root") != str(destination):
        raise ImagePipelineError("Previous image import used a different patch_root; use the same destination")
    previous = {_rom_relative(item) for item in prior.get("files", [])}
    unmanaged = [name for name in changed if (destination / name).exists() and name not in previous]
    if unmanaged:
        raise ImagePipelineError(f"Refusing to overwrite unmanaged patch files: {', '.join(unmanaged)}")

    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="image-import-", dir=image_root) as temporary:
        temp = Path(temporary)
        for name, pngs in changed.items():
            raw = image_root / "raw" / name
            output = temp / "built" / name
            output.parent.mkdir(parents=True, exist_ok=True)
            if manifest["assets"][name]["kind"] == "pic":
                _run([extractor, str(raw), str(output), "-replace", str(pngs[0])])
            else:
                rel = PurePosixPath(name)
                replacement_dir = temp / "replacement" / rel.with_suffix("")
                replacement_dir.mkdir(parents=True, exist_ok=True)
                for png in pngs:
                    shutil.copy2(png, replacement_dir / png.name)
                prefix = replacement_dir / (rel.stem + ".png")
                adapted = _txa_for_extractor(raw, temp / "normalized" / name)
                _run([extractor, str(adapted), str(output), "-replace", str(prefix)])
                _restore_txa_flags(output, raw)
            expected_magic = b"PIC4" if manifest["assets"][name]["kind"] == "pic" else b"TXA4"
            if output.open("rb").read(4) != expected_magic:
                raise ImagePipelineError(f"Repacked container has wrong format: {output}")

        removed = []
        for name in sorted(previous - set(changed)):
            old = destination / name
            if old.is_file():
                old.unlink()
                removed.append(str(old))
        outputs = []
        for name in sorted(changed):
            built = temp / "built" / name
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(built, target)
            outputs.append(str(target))
    _write_json(state_path, {"patch_root": str(destination), "files": sorted(changed)})
    return {"changed_assets": sorted(changed), "output_files": outputs, "removed_files": removed}


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list", help="List patchable image containers")
    listing.add_argument("--rom", required=True)
    listing.add_argument("--sdu", default="sdu")
    exporting = sub.add_parser("export", help="Export editable menu/PIC PNGs")
    exporting.add_argument("--rom", required=True)
    exporting.add_argument("--project", required=True)
    exporting.add_argument("--sdu", default="sdu")
    exporting.add_argument("--extractor", default="EnterExtractor")
    exporting.add_argument("--all-pictures", action="store_true")
    exporting.add_argument("--select", action="append", default=[])
    previews = sub.add_parser("previews", help="List editable PNG preview paths")
    previews.add_argument("--project", required=True)
    importing = sub.add_parser("import", help="Repack changed PNGs into patch files")
    importing.add_argument("--project", required=True)
    importing.add_argument("--patch-root", required=True)
    importing.add_argument("--extractor", default="EnterExtractor")
    args = parser.parse_args()
    try:
        if args.command == "list":
            result = list_image_assets(args.rom, args.sdu)
        elif args.command == "export":
            manifest = export_images(args.rom, args.project, args.sdu, args.extractor,
                                     selected=args.select or None, include_pictures=args.all_pictures)
            result = {"assets": len(manifest["assets"]), "previews": preview_images(args.project)}
        elif args.command == "previews":
            result = preview_images(args.project)
        else:
            result = import_images(args.project, args.patch_root, args.extractor)
    except (ImagePipelineError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Image pipeline error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
