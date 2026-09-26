# Pixel Forge

A batch image format converter with a web interface. Drop in any number of
images, pick an output format, resize/rotate as needed, and get back
converted files individually or as a single ZIP.

Built as part of a portfolio series applying the [Google IT Automation with
Python](https://www.coursera.org/professional-certificates/google-it-automation)
methodology to real, testable software projects.

![Pixel Forge — dark mode](docs/screenshots/dark-mode.png)
![Pixel Forge — light mode](docs/screenshots/light-mode.png)

## Features

- **Reads almost any image** — JPEG, PNG, **HEIC/HEIF (iPhone photos)**,
  **AVIF**, WEBP, GIF, TIFF, BMP, ICO, PSD, TGA, JPEG 2000 and more
- **Writes 10 formats** — JPEG, PNG, WEBP, AVIF, HEIC, GIF, BMP, TIFF, ICO
  and PDF
- **Handles tricky images** — CMYK print files, 16-bit scans, palette
  images with transparency, and 1-bit black & white all convert cleanly;
  transparency is flattened onto white (not black) for formats that
  can't store it
- **Keeps animations** — animated GIF/WEBP/PNG stay animated when the
  output format supports it
- **Keeps colour accurate** — embedded colour profiles (e.g. Display P3
  on iPhone photos) are carried over, and JPEG/WEBP/AVIF/HEIC are saved
  at high quality
- **Original size by default** — only resizes when you pick a preset or
  type a size
- **Resize** with either **Fit** (preserves aspect ratio) or **Stretch**
  (forces exact dimensions), plus an **Auto** option for anyone unsure which
  to pick
- **Size presets** — common resolutions from icon sizes (128×128) up through
  8K DCI cinema (8192×4320), grouped by category
- **Rotate** in 90° increments
- **Batch-safe by design** — one corrupted or unreadable file in a batch of
  hundreds never crashes the whole run; it's skipped and reported with a
  clear, plain-language message (not a stack trace), and everything else
  still converts
- **Drag-and-drop or click-to-browse** file selection, additive (adding more
  files doesn't wipe out what you already selected)
- **Fast on big batches** — files are converted in parallel, the page only
  receives small previews, and **Download All** zips the results already
  converted instead of redoing the work (28 iPhone photos to 8K PNG: ~14 s)
- **Individual downloads** per converted file, or **Download All** as a ZIP
- **Dark/light theme**, persisted across visits, no flash of the wrong theme
  on reload

## Tech stack

Python, Flask, Pillow, pillow-heif (HEIC support), vanilla JS (no
frontend framework), pytest.

## Setup

Requires Python 3.10+.

### Linux / macOS

```bash
git clone https://github.com/Aayush29052006/Pixel-Forge.git
cd Pixel-Forge
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Windows (PowerShell)

```powershell
git clone https://github.com/Aayush29052006/Pixel-Forge.git
cd Pixel-Forge
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Running it

```bash
python run.sh
```

Then open **http://127.0.0.1:5050** in a browser. Port 5050 is used
deliberately instead of Flask's default 5000, to avoid clashing with other
local projects that may already be running on 5000.

## Running tests

```bash
pytest -v
```

157 tests across the conversion engine, the batch runner, and the web layer.

## Settings

All optional, set as environment variables when starting the app, e.g.
`PIXELFORGE_WORKERS=16 python run.sh`:

| Variable | Default | What it does |
|---|---|---|
| `PIXELFORGE_MAX_UPLOAD_MB` | 300 | Largest total upload per batch |
| `PIXELFORGE_WORKERS` | CPU cores, max 8 | Files converted at the same time. More is faster but uses more memory (8K output: ~2.3 GB at 8, ~3.3 GB at 16) |
| `PIXELFORGE_RESULT_CACHE_MB` | 2048 | Memory kept for converted results so downloads and the ZIP don't need a re-conversion. Older batches are dropped past this limit; the newest is always kept |

## Known limits

These aren't bugs — they're deliberate, sane defaults for a local
single-user tool:

- **~999 files per batch upload.** This comes from Werkzeug's built-in
  `MAX_FORM_PARTS` protection (1000 parts per request, where each file plus
  each form field counts as one part) — a security limit against malicious
  multipart requests, not something Pixel Forge imposes itself.
- **300 MB total upload size per batch**, configurable without touching
  code:
  ```bash
  PIXELFORGE_MAX_UPLOAD_MB=1000 python run.sh
  ```
- **Resizing upscales, but doesn't add detail.** Picking a target size
  larger than the source image (e.g. converting a 500×500 photo to 8K) will
  succeed, but the result is interpolated, not AI-upscaled — it'll look
  soft, not sharp.
- **Target size is capped at 16384 px per side**, and very large source
  images (over ~256 megapixels) are refused to protect memory.
- **Resizing needs both width and height.** Filling in only one leaves
  the image at its original size.
- **Results stay available until newer batches push them out** of the
  result cache (see Settings). If that happens, downloading shows "These
  results have expired" — just convert again. Restarting the app also
  clears them.

## More screenshots

| | |
|---|---|
| ![File selection state](docs/screenshots/file-selection.png) File selection before converting | ![Light mode results](docs/screenshots/light-mode-results.png) Light mode with results |
| ![Size presets](docs/screenshots/preset-dropdown.png) Size preset dropdown | ![Mixed batch results](docs/screenshots/mixed-results.png) A batch with one success, one error |
| ![Error toast](docs/screenshots/error-toast.png) Error notification | |

## Project structure

```
Pixel-Forge/
├── src/pixelforge/
│   ├── core.py              # pure conversion engine (bytes in, bytes out)
│   ├── batch.py              # batch runner: parallel, per-file error handling, summary report
│   └── webapp/
│       ├── __init__.py       # Flask app factory
│       ├── routes.py         # /, /api/convert, /api/batch/<id>/..., /api/convert/zip
│       ├── results.py        # in-memory store of converted batches
│       ├── static/img/       # the one raster asset the app uses (error icon)
│       └── templates/
│           └── index.html    # the whole frontend: HTML/CSS/JS, no build step
├── tests/                    # pytest suite, synthetic images generated in-memory
├── design-reference/
│   └── mockup.html           # approved visual reference the real UI was built to match
└── run.sh                    # starts the dev server on port 5050
```

## License

MIT — see [LICENSE](LICENSE).
