"""Exercise downloaded Windows tools and a game-asset-free Ruby ROM build."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from app import _patch_kaleido_binary_io  # noqa: E402


def run(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120
    )
    if result.returncode:
        raise RuntimeError(f"{' '.join(args[:2])} exited {result.returncode}: {(result.stdout + result.stderr)[-1500:]}")
    return result


def check_tools(tools_dir: Path) -> None:
    sdu = tools_dir / "sdu.exe"
    extractor = tools_dir / "EnterExtractor.exe"
    if not sdu.is_file() or not extractor.is_file():
        raise RuntimeError("bootstrap_tools.py did not install both Windows executables")

    sdu_help = run([str(sdu), "--help"])
    if "Usage:" not in sdu_help.stdout + sdu_help.stderr:
        raise RuntimeError("sdu.exe started but did not print its CLI help")

    # EnterExtractor uses exit code 1 when invoked without the two required
    # filenames. Its usage message proves the executable and runtime loaded.
    result = subprocess.run(
        [str(extractor)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30
    )
    if "Usage:" not in result.stdout + result.stderr:
        raise RuntimeError(
            f"EnterExtractor.exe did not reach its CLI: exit {result.returncode}, "
            f"output {(result.stdout + result.stderr)[-1000:]}"
        )
    print("sdu.exe and EnterExtractor.exe launch successfully")


def check_ruby_compiler(source_dir: Path, ruby: str) -> None:
    run([ruby, "--version"])
    patch_source = source_dir / "kaleido2-patch"
    kaleido_source = source_dir / "kaleido"
    if not (patch_source / "compile.rb").is_file() or not (kaleido_source / "rom-repack/kal_real.rb").is_file():
        raise RuntimeError("bootstrap_tools.py did not install both compiler sources")

    with tempfile.TemporaryDirectory(prefix="kaleido-ci-") as directory:
        root = Path(directory)
        patch_copy = root / "kaleido2-patch"
        kaleido_copy = root / "kaleido"
        shutil.copytree(patch_source, patch_copy)
        shutil.copytree(kaleido_source, kaleido_copy)
        _patch_kaleido_binary_io(kaleido_copy, patch_copy)
        run([ruby, "-c", str(patch_copy / "compile.rb")])
        run([ruby, "-c", str(kaleido_copy / "rom-repack/kal_tl.rb")])

        rom_source = root / "synthetic-rom-source"
        rom_source.mkdir()
        (rom_source / "main.snr").write_bytes(b"replaced by compiler")
        marker = b"binary\r\n\x1a still present\r\n"
        (rom_source / "sample.bin").write_bytes(marker)
        output = root / "synthetic.rom"
        scenario = root / "synthetic.rb"
        scenario.write_text(
            'def raw_apply(snr)\n  snr.write_script("\\x50", 0)\nend\n', encoding="utf-8"
        )

        run([
            ruby,
            str(kaleido_copy / "rom-repack/kal_real.rb"),
            str(scenario),
            str(rom_source),
            str(output),
        ], cwd=kaleido_copy / "rom-repack")
        payload = output.read_bytes()
        if not payload.startswith(b"ROM2") or b"SNR " not in payload or marker not in payload:
            raise RuntimeError("Ruby did not compile the scenario and preserve binary ROM asset bytes")
        print(f"Ruby compiled a synthetic {len(payload):,}-byte ROM2 with intact binary payload")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tools-dir", type=Path, default=REPO / "tools")
    parser.add_argument("--source-dir", type=Path, default=REPO / "dependencies")
    parser.add_argument("--ruby", default="ruby")
    parser.add_argument("--skip-tool-check", action="store_true", help="for local non-Windows verification")
    args = parser.parse_args()
    if not args.skip_tool_check:
        check_tools(args.tools_dir)
    check_ruby_compiler(args.source_dir, args.ruby)


if __name__ == "__main__":
    main()
