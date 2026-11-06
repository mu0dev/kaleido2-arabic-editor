# Image translation workflow

The game's dialogue and many UI strings are separate. Japanese lettering is
painted into texture images such as `title.txa` and `config.txa`. A translator
can add Arabic text in the local web editor's canvas, optionally cover old
Japanese with a solid rectangle, or upload a PNG made in an external image
editor. Changed PNGs can then be rebuilt as game-format image overrides.

## What the archive contains

The tested *Kaleidoscope of Phantom Prison II* `data.rom` contains 14 TXA
texture atlases and 191 standalone PIC pictures. The TXAs cover title,
settings, save/load, card selection, log view, manual, and other UI. Exporting
all 14 TXAs yielded 181 individual PNG previews; many are decorations, while
some contain Japanese text. For example, `title_menu_focus.png` contains the
main-menu labels in the focused state, `config_help_config.png` contains settings help labels, and
the manual atlas includes 15 illustrated pages with printed instructions.
The 191 PICs are in `picture/bg`, `picture/card`, `picture/cg`, and
`picture/cutin`. Use preview paths to decide which pictures need translation.

Character bustups (`.bup`), transition masks (`.msk`), videos (`.mp4`), and
font files (`.fnt`) are outside this image importer. EnterExtractor can decode
some of them, but cannot rebuild them with its `-replace` mode. Dialogue and
script text in `main.snr` are handled by the text pipeline.

## Dependencies

- A local, legally obtained `data.rom` extracted from the user's game.
- The Windows `sdu.exe` from [DCNick3/shin](https://github.com/DCNick3/shin/releases/tag/v0.8.1) for
  listing and extracting ROM entries.
- The Windows `EnterExtractor.exe` from
  [07th-mod/enter_extractor](https://github.com/07th-mod/enter_extractor/releases/tag/v1.0.0) for PNG
  conversion and rebuilding PIC/TXA containers. `setup.cmd` downloads both
  tools and verifies their release ZIP hashes. The Python wrapper adjusts
  Gerokasu 2's TXA header flags before passing them to this
  older tool and restores the original flags afterward. This matters for
  `title.txa`, whose unadjusted value makes EnterExtractor crash.

## Command line

Run these commands in Command Prompt from the editor folder. Replace the ROM
path with your own extracted file. No source game images are distributed with
the editor.

```bat
.venv\Scripts\python.exe -m engine.images list --rom C:/Kaleido2/game/data.rom --sdu tools/sdu.exe

rem Export the menu/UI atlases into project/images/editable/txa/.
.venv\Scripts\python.exe -m engine.images export ^
  --rom C:/Kaleido2/game/data.rom --project project ^
  --sdu tools/sdu.exe --extractor tools/EnterExtractor.exe

rem Export every PIC as well as the menu atlases.
.venv\Scripts\python.exe -m engine.images export ^
  --rom C:/Kaleido2/game/data.rom --project project ^
  --sdu tools/sdu.exe --extractor tools/EnterExtractor.exe --all-pictures

rem List previews and build only changed PIC/TXA files.
.venv\Scripts\python.exe -m engine.images previews --project project
.venv\Scripts\python.exe -m engine.images import ^
  --project project --patch-root project/patch-images ^
  --extractor tools/EnterExtractor.exe
```

`PROJECT/images/manifest.json` records each exported PNG's original hash and
dimensions. `export` preserves existing editable PNGs, so it can be run again
to add more assets without losing edits. `previews` marks each PNG as modified
when its bytes differ from that original hash. The web editor can serve each
returned `path` as an image URL after validating it is inside
`PROJECT/images/editable`.

The browser canvas keeps the original pixel dimensions. Arabic text is placed
by clicking the image or entering X/Y values, with font size and color fields.
A solid cover rectangle can be sized by dragging. The Save image button
uploads a flattened PNG to the local project; the external upload route uses
the same endpoint. The canvas offers a quick way to translate plain menu text.
Complex backgrounds and manual pages may need an external graphics editor.

`import` accepts PNG edits at the original dimensions. It writes only modified
containers to a dedicated `patch-images` tree with the same relative paths
that exist inside `data.rom`, such as `patch-images/title.txa` and
`patch-images/picture/card/カード裏面.pic`. A build script can copy this tree into
the repacker's `rom_source` directory before compiling `patch.rom`. Reverting
a PNG exactly to its exported bytes removes that container's image override on
the next import. The importer tracks its own output files and refuses to
overwrite untracked files in its destination.

## Editing guidance

- Keep each PNG's pixel dimensions. The importer rejects resizing because
  layout positions in the game script may assume the original size.
- Preserve transparent areas and button-state arrangements in each atlas.
  Title and settings text may have normal, focused, and shadow textures that
  need matching Arabic art.
- The importer records PNG modifications, not semantic translation progress.
  A reviewer should inspect the rendered menu in the game for clipping,
  direction, and focus-state differences.
- TXA repacking recompresses the atlas. A copy of the original container is
  retained under `PROJECT/images/raw`; the image override is separate and can
  be removed to revert the game.
