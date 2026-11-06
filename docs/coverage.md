# Kaleidoscope of Phantom Prison II: localization coverage audit

Audited the user's title `0100451020714000` from the extracted `data.rom` (965,442,560 bytes), the checked out `kaleido2-patch` sources, and representative decoded assets. This is a resource inventory for a translation editor, not a claim that every surface has already been translated.

## Resource map

The game Program NCA RomFS contains `data.rom` and `copyright.bmp`. The latter is a 384×60 copyright mark with publisher names. `data.rom` contains **4,410 files**:

| Resource | Count | Purpose / visible text | Editing support in existing pipeline |
| --- | ---: | --- | --- |
| `main.snr` | 1 | Dialogue, speaker names, choices, save chapter names, gallery/BGM display metadata | **Yes**, `kal_tl.rb` compiles from `base/main.rb` plus `dialogue.txt`; `compile.rb` packages generated SNR. |
| `newrodin-medium.fnt`, `system.fnt` (FNT6 v1) | 2 | Text rendering; originals contain **zero** Arabic codepoints | **Package only.** `compile.rb` accepts arbitrary files in `rom_source`, but does not create FNT6. Current separate Arabic PUA font tool creates replacement fonts. |
| Root `*.txa` (TXA4) | 14 archives, 200 texture entries, 181 decoded PNG previews | Most menus, labels, manual pages, logos, captions; many Japanese strings are baked into pixels | **Editor support:** browse, overlay or upload a PNG, repack modified archives. A modified `title.txa` mounted in a Suyu title-menu smoke test; visual Arabic menu replacement still needs review. |
| `picture/**/*.pic` (PIC4) | 191 | Backgrounds, CG, cut-ins, cards; some may have baked words/numbers | **Editor support:** browse, overlay or upload a PNG, and repack modified PICs. Static PIC round-trip passed; a modified PIC has not been checked in Suyu. |
| `movie/*.mp4` | 2 | Opening and ending video, with baked Japanese title/character intro/credits text | **Raw override only.** Re-encode/render text onto frames externally; `compile.rb` has no video editor. |
| `voice/*.nxa`, `se/*.nxa`, `bgm/*.nxa` | 4,068 / 48 / 21 = 4,137 | Voice, effects, music; no directly visible text | **Raw override only.** Dubbing/audio editing is outside current compiler. Keep SNR audio IDs and archive paths stable. |
| `bustup/m/*.bup` | 46 | Character artwork/expression layers | **Raw override only.** No known dialogue text; inspect for incidental art text if aiming for exhaustive localization. |
| `*.msk`, `mask/*.msk` | 2 root + 14 nested = 16 | Visual transition masks | **Raw override only.** No known text. |
| `sysse.bin` | 1 | System sound data | **Raw override only.** No known text. |

PIC groups: `picture/bg` 29, `picture/card` 40, `picture/cg` 47, `picture/cutin` 75. TXA texture counts: `adv` 7, `bgmmode` 13, `bupmode` 39, `cardselect` 6, `cgmode` 40, `config` 14, `effects` 6, `logview` 20, `manual` 22, `msgtex` 3, `saveload` 13, `splash` 4, `systex` 6, `title` 7.

## SNR text surfaces

`dialogue.txt` has **5,926 unique numeric IDs**: 5,920 story entries `7`–`5926` and six debug/test IDs `16777217`–`16777222`. There are 19 `# section` comments that group story progress. Each editable row is `ID<TAB>message`. The message includes the speaker label before the first `@r`, then body and inline commands. Among all rows there are 23 distinct nonblank speaker labels and 1,858 rows with an empty speaker label (narration or unlabeled speech). There are 4,063 `@v` voice references and 5,952 `@r` separators.

Control syntax present in those rows: `@r`, `@v`, `@k`, `@z`, `@x`, `@b`, `@s`, `@a`, `@|`, `@<`, `@>`. The tool must protect these when editing, and must preserve the numeric IDs. `kal_tl.rb` reads tab-delimited rows; tabs inside translations would corrupt parsing. The compiler currently leaves automatic line layout disabled (`layouted = filtered`), so Arabic wrapping must be preprocessed or added to the editor. Do not translate filenames or voice IDs embedded in SNR tables.

`base/main.rb` contains all 5,926 `MSGSET` references and additional literals outside `dialogue.txt`:

| Source construct | Count | Why it matters |
| --- | ---: | --- |
| `s.ins SAVEINFO` | 19 | Save/autosave chapter labels; edit Ruby source or expose them as a separate translation catalog. |
| `s.ins SELECT` | 6 | Choice option strings (four debug navigation selections, two repeated gameplay selections). Options are separated by embedded `\u0000`; edit Ruby source/catalog. |
| `snr.bgm` | 21 | Second argument is a BGM display title; first argument is an asset ID. Some titles also appear baked in `bgmmode/title0.png`, so edit both. |
| `snr.table8_entry` | 29 | Picture Box thumbnail keys. All 29 names exactly match sprites inside `cgmode.txa`; they are **read-only** in the editor. The numeric arguments reference CG/cut-in picture IDs separately. Translate visible gallery UI artwork through the image editor. |

Three quoted `VOICEPLAY` arguments are audio filenames, not display text. Most Japanese strings in `snr.bg` and `snr.bustup` declarations are **asset identifiers** and should not be translated. The other SNR table entries found are numeric or asset references. This classification is based on the available Ruby source; runtime review is still needed to catch engine-generated labels.

The `table8_entry` labels are internal thumbnail lookup keys, not established player-facing titles. Upstream Shin's `PictureBoxInfoItem` format defines each name as the texture name to load from `cgmode.txa`, and its picture IDs as separate references into the picture table. The game's 29 keys match exactly 29 of the 40 decoded `cgmode.txa` sprites; the other 11 are UI elements (`caption`, `help_cgmode`, `top`, etc.). A decoded named sprite contains artwork only. Changing a key alone would break its thumbnail lookup. Adding Arabic aliases to the TXA is also unavailable: TXA texture names use Shin's Shift-JIS string format, which cannot encode Arabic or the private-use glyphs used by this translation. The existing keys should remain locked; translate visible gallery artwork in the TXA sprites instead.

## Baked image and video text confirmed by visual inspection

Decoded with `sdu texture-archive decode --utf8-names`:

- `title.txa`: `menu_focus.png` holds Japanese main-menu labels; `logo.png` contains the title artwork. `menu_normal.png` alone contains blank button art, so replacing only that texture will not translate the menu.
- `config.txa`: `category.png`, `left.png`, `right.png`, and `help_config.png` hold Japanese setting names, values, and control hints.
- `adv.txa`: `sysmenu_normal.png` and related sprites hold the in-game system-menu labels.
- `manual.txa`: fifteen numbered pages `001.png`–`015.png` contain Japanese instructional text; the archive also has caption/help textures.
- `saveload.txa`, `cardselect.txa`, `cgmode.txa`, `bgmmode.txa`, `bupmode.txa`, `logview.txa`, and `splash.txa` contain visible text in captions, lists, help, or splash images. `bgmmode/title0.png` contains a baked song list. `splash/caution.png` is a Japanese warning.
- `effects.txa`, `msgtex.txa`, and `systex.txa` were not confirmed to contain translatable text; keep them in the inventory for full visual review.
- One decoded PIC card (`picture/card/１時間.pic`) shows the English text “1 hour”. This does not prove all 191 PICs are text-free; backgrounds, cards, CG, and cut-ins need an image-by-image visual audit.
- Sample frames of `movie/op2.mp4` at 30 s show Japanese character-intro text, and frames of `movie/ed.mp4` at 30/90 s show Japanese title/credits text. Both need video editing for a complete localization.

## Build and verification status

The upstream patch compiler leaves its built-in `PICTURES` and `GUI` replacement lists empty. This editor has a separate image pipeline: it extracts TXA/PIC files from the user's `data.rom`, decodes editable PNGs, repacks changed assets, and places them in `rom_source` for the compiler. A same-image PIC4 rebuild and TXA4 `config_category` rebuild passed, and the rebuilt TXA decoded to the same 14 textures with a pixel-for-pixel category match. A smoke patch containing a modified `title.txa` mounted in Suyu and reached the title menu; the test changed an inconspicuous pixel, so an Arabic menu still needs visual review.

An earlier Arabic proof patch used 555 private-use glyphs and 68 translated prologue lines; Suyu loaded it through LayeredFS and displayed Arabic dialogue. The editor now rebuilds the word/font map from saved translations and validates font coverage and dialogue control markers on each export. Full-game visual review still depends on completed translations and checking each changed screen in Suyu.

## Editor coverage checklist

1. **Structured dialogue view:** all 5,926 IDs, speaker, Japanese source, Arabic translation, section, voice ID, protected inline commands, search/filter, untranslated count.
2. **SNR metadata view:** 19 save labels, the options in six selection instructions, 21 BGM display titles, and 29 read-only gallery thumbnail keys. Keep asset IDs separate from display text.
3. **Image asset view:** 181 decoded TXA previews and 191 PICs with editable replacement PNGs and archive/sprite identity. Manual pages and menu sprites should be prioritized.
4. **Video assets:** opening and ending MP4s can be previewed and replaced in the editor. Frame editing and timed credits still need an external video editor.
5. **Export validation:** preserve command syntax and IDs, shape/wrap Arabic into the PUA font mapping, emit FNT6 + SNR + selected image/video overrides, parse the resulting ROM, then test it in Suyu. Report image and video gaps explicitly when exporting.
