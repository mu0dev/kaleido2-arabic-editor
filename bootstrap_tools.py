"""Download pinned Windows utilities and public patch compiler sources."""

from __future__ import annotations

import argparse
import hashlib
import io
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.request import Request, urlopen
from zipfile import ZipFile


@dataclass(frozen=True)
class Tool:
    name: str
    url: str
    archive_member: str
    sha256: str


TOOLS = (
    Tool(
        "sdu.exe",
        "https://github.com/DCNick3/shin/releases/download/v0.8.1/sdu-x86_64-pc-windows-msvc.zip",
        "sdu.exe",
        "5a56b5f4b02e8317178c17c1a9677e2020f0e3d566e4f4d089cb8094e6a33b6e",
    ),
    Tool(
        "EnterExtractor.exe",
        "https://github.com/07th-mod/enter_extractor/releases/download/v1.0.0/windows.zip",
        "EnterExtractor.exe",
        "a0ca283a76fc88f930d0d02447aa6ec00ca0edde3db5b45c63b17081e622c037",
    ),
)


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    archive_root: str
    required_file: str
    sha256: str


SOURCES = (
    Source(
        "kaleido2-patch",
        "https://gitlab.com/Neurochitin/kaleido2-patch/-/archive/4f4aa719f7d61b33c58e0360071e6b77f2b9e99a/kaleido2-patch-4f4aa719f7d61b33c58e0360071e6b77f2b9e99a.zip",
        "kaleido2-patch-4f4aa719f7d61b33c58e0360071e6b77f2b9e99a",
        "compile.rb",
        "11c1be5aa2cc2853238d6ee761b4139774f0dbb4afb834b0499f4514182df975",
    ),
    Source(
        "kaleido",
        "https://gitlab.com/Neurochitin/kaleido/-/archive/10393ff655f44577314f9585e6d696854f14e1b6/kaleido-10393ff655f44577314f9585e6d696854f14e1b6.zip",
        "kaleido-10393ff655f44577314f9585e6d696854f14e1b6",
        "rom-repack/toolkit.rb",
        "d9bd61f2e9876bc8573b845d848317dd2d37acff2fd856c3309dc5843782906a",
    ),
)


def download_verified(name: str, url: str, expected_sha256: str) -> bytes:
    print(f"Downloading {name} from its official source ...", flush=True)
    request = Request(url, headers={"User-Agent": "Kaleido2-Arabic-Editor/1.0"})
    with urlopen(request, timeout=90) as response:
        archive = response.read()
    actual = hashlib.sha256(archive).hexdigest()
    if actual != expected_sha256:
        raise RuntimeError(f"{name} download hash mismatch: expected {expected_sha256}, got {actual}")
    return archive


def install_tool(tool: Tool, target_dir: Path) -> Path:
    destination = target_dir / tool.name
    if destination.is_file():
        print(f"Already installed: {destination}")
        return destination
    archive = download_verified(tool.name, tool.url, tool.sha256)
    with ZipFile(io.BytesIO(archive)) as bundle:
        executable = bundle.read(tool.archive_member)
    if not executable.startswith(b"MZ"):
        raise RuntimeError(f"{tool.name} archive does not contain a Windows executable")
    target_dir.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_bytes(executable)
    temporary.replace(destination)
    print(f"Installed: {destination}")
    return destination


def install_source(source: Source, target_dir: Path) -> Path:
    destination = target_dir / source.name
    if destination.exists():
        if (destination / source.required_file).is_file():
            print(f"Already installed: {destination}")
            return destination
        raise RuntimeError(f"Incomplete source checkout at {destination}; remove it and retry")
    archive = download_verified(source.name, source.url, source.sha256)
    target_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{source.name}-", dir=target_dir) as temporary:
        staged = Path(temporary) / source.name
        staged.mkdir()
        with ZipFile(io.BytesIO(archive)) as bundle:
            for member in bundle.infolist():
                parts = PurePosixPath(member.filename).parts
                if not parts or parts[0] != source.archive_root or ".." in parts:
                    raise RuntimeError(f"Unsafe path in {source.name} archive: {member.filename}")
                if len(parts) == 1:
                    continue
                target = staged.joinpath(*parts[1:])
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(bundle.read(member))
        if not (staged / source.required_file).is_file():
            raise RuntimeError(f"{source.name} archive lacks {source.required_file}")
        staged.replace(destination)
    print(f"Installed: {destination}")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-dir", type=Path, default=Path(__file__).resolve().parent / "tools")
    parser.add_argument("--source-dir", type=Path, default=Path(__file__).resolve().parent / "dependencies")
    args = parser.parse_args()
    for tool in TOOLS:
        install_tool(tool, args.target_dir)
    for source in SOURCES:
        install_source(source, args.source_dir)


if __name__ == "__main__":
    main()
