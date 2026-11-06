# Kaleidoscope II Arabic translation editor

A local browser editor for building an Arabic patch for *Kaleidoscope of Phantom Prison II* (title ID `0100451020714000`). The editor stores translations in a separate project directory and builds a Suyu LayeredFS `patch.rom`. It does not translate the game automatically or include game files.

## Start the editor

Clone this repository, install the dependencies below, then copy `config.example.json` to `config.local.json` and fill in paths to your own extracted game files and build tools. Start with `./run.sh` on Linux or `run.cmd` on Windows, then open the address it prints (`http://127.0.0.1:8778/` by default). Keep the project directory named in your local configuration: it holds saved edits and extracted image previews. `config.local.json`, game files, and generated patches are excluded from Git.

## Set up

Use your own extracted copy of the game. You need `data.rom`, `newrodin-medium.fnt`, and `system.fnt`, plus local checkouts of the [`kaleido2-patch`](https://gitlab.com/Neurochitin/kaleido2-patch) repository and the [`kaleido`](https://gitlab.com/Neurochitin/kaleido) repository on its `kaleido2-repack` branch. The patch checkout supplies `dialogue.txt` and `base/main.rb`. The game files and translated project stay outside this tool's source bundle.

Install Python 3.10+ with the packages in `requirements.txt`, a Noto Sans Arabic Regular TTF, Ruby compatible with the patch compiler, [`sdu`](https://github.com/AuroraWright/shin), and [`EnterExtractor`](https://github.com/DCNick3/EnterExtractor). `sdu` reads game archive entries; `EnterExtractor` converts image assets. Suyu is needed to run the result. Pillow uses libraqm for Arabic shaping where available; the included reshaping and bidirectional text packages provide a Windows fallback. Install the Python dependencies with `python3 -m pip install -r requirements.txt` on Linux, or use the Windows commands below.

Copy `config.example.json` to `config.local.json`. Edit every path for your machine. `project_dir` should be a writable directory for translations, extracted previews, and builds. `suyu_load_dir` is Suyu's `load` directory; its location can vary with your install. `original_*` and `data_rom` point to your local source files. `arabic_font_path` points to the Noto Sans Arabic Regular TTF. `patch_source`, `kaleido_path`, `sdu_bin`, `enter_extractor_bin`, and `ruby_bin` point to tools or checkouts on your machine. If Ruby is in a custom runtime, optional `ruby_lib_dir` and `ruby_load_paths` can be set as well.

### Linux

Install the Python dependencies, copy and edit the configuration, then run `./run.sh`. The common Noto Sans Arabic path on Linux is `/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf`; set `arabic_font_path` to its actual location. To use another local port, run `./run.sh 8780`.

### Windows

Install Python 3.10+, Ruby, and Windows builds of `sdu` and `EnterExtractor`. In Command Prompt, from this repository's directory:

```bat
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
copy config.example.json config.local.json
```

Edit `config.local.json` before running `run.cmd`: use absolute paths with forward slashes, such as `C:/Games/Kaleido/data.rom`, which are valid in JSON. Set `arabic_font_path` to your Noto Sans Arabic Regular TTF, `ruby_bin` to `ruby.exe`, `sdu_bin` and `enter_extractor_bin` to their Windows executables, and `suyu_load_dir` to the actual Suyu `load` directory on your installation. Point `patch_source` and `kaleido_path` to the required local checkouts. Then run `run.cmd`. Close the game before installing a patch so Suyu does not lock the old file. Run `run.cmd 8780` to choose another local port. The server binds to localhost by default.

## Translate and build

The catalog covers **5,926 dialogue IDs**, **23 speaker names**, **70 editable UI strings**, **29 read-only gallery asset keys**, **372 PNG previews** after extracting all images (181 from 14 menu/UI atlases and 191 standalone pictures), and **2 videos**. The image count is zero in a new project until you click **Extract all images**. Translation coverage numbers count saved edits, not reviewed quality.

1. **Dialogue:** Search or filter the script, edit the Arabic body, and save each entry. The editor shows the Japanese source, speaker, voice reference, and an immediate RTL text preview. Keep inline commands such as `@r` where they are needed; the exporter validates required control commands and line IDs. Translate speaker labels once in the **Speaker** field beside a line to apply that name across its lines. Empty speaker labels are narration.
2. **UI strings:** Edit save labels, choice text, and BGM display titles. The 29 gallery asset keys are shown for context and cannot be changed because they identify assets. Baked menu/gallery text belongs in the image editor.
3. **Images:** Extract all game images, browse thumbnails, then add Arabic text in the canvas. Use a solid cover rectangle where needed, and **Save image** to store the rendered PNG. You can also upload an externally edited PNG. Keep original dimensions, alpha, and button states. The builder includes only changed images. See [docs/images.md](docs/images.md) for the image pipeline and limits.
4. **Videos:** Preview `movie/op2.mp4` and `movie/ed.mp4`; edit frames and credits in a video editor, then upload replacement MP4s. The browser does not edit video frames.
5. **Export:** Click **Build patch**. The patch is written to `project_dir/build/patch.rom`; details and errors are in `project_dir/build/build.log`. Then click **Install to Suyu**. This copies the patch to `<suyu_load_dir>/0100451020714000/<mod_name>/romfs/patch.rom`. The installer rejects another active `patch.rom` mod for this title to avoid conflicting overrides. Close and restart the game in Suyu after installation.

Edits and image previews update immediately **in the browser**. The running game does **not** hot reload: build, install, and restart it to see changes in Suyu. Keep the project directory to continue translating; its JSON edit files are separate from the original game and patch sources.

## Development verification

The Linux launcher served the local editor in the development environment. Twelve asset-free checks, including an HTTP startup test, passed on both Ubuntu and Windows in GitHub Actions. A separate Linux smoke project saved Arabic dialogue, a speaker name, a save title, and a modified PNG through the editor API; the build and Suyu installer completed. Suyu mounted that generated patch and reached the title menu. Earlier in-game checks also displayed Arabic dialogue and a speaker name. These checks establish a working editing and patch pipeline on the tested Linux setup. The Windows game build path has not been tested end to end with game assets on Windows. The full game still needs translator work and in-game review of each changed screen.

## Limits to review in game

- Arabic text uses generated private-use glyphs in replacement FNT6 fonts because the original fonts have no Arabic glyphs. The exporter checks character coverage and preserved commands. Ruby-style pronunciation annotations (`@b`, `@<`, `@>`) must be flattened into ordinary text in translated lines. The game's text reveal and line layout still require visual review.
- A source inventory found menus and manual text baked into texture images. The editor exposes TXA/PIC PNGs; character bustups and transition masks are outside this image importer. Video text needs external editing. No dubbing or audio editing is provided.
- Dynamic labels generated by the game engine may remain untranslated. The catalog is an inventory of the inspected script and assets, not a guarantee that every screen is localized. Check choices, saves, menus, video, and long lines in Suyu as translations are added.
- This tool expects already extracted, user-owned game files. It does not acquire a game, extract an XCI, or distribute copyrighted game assets, keys, original images, audio, or video.
