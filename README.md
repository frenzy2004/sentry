# SentrySearch

Semantic search over video footage. Type what you're looking for, get a trimmed clip back.

**New:** [Blur objects in your videos](#redact-with-sentryblur) with [SentryBlur](https://github.com/ssrajadh/sentryblur), composes directly with SentrySearch

[<video src="https://github.com/ssrajadh/sentrysearch/raw/main/docs/demo.mp4" controls width="100%"></video>](https://github.com/user-attachments/assets/baf98fad-080b-48e1-97f5-a2db2cbd53f5)

## Table of Contents

- [How it works](#how-it-works)
- [Getting Started](#getting-started)
- [B-roll App Quick Start for Testers](#b-roll-app-quick-start-for-testers)
- [Usage](#usage)
  - [Init](#init)
  - [Index footage](#index-footage)
  - [Search](#search)
  - [B-roll](#b-roll)
  - [Web UI](#web-ui)
  - [Portable demo index](#portable-demo-index)
  - [Friend testing setup](#friend-testing-setup)
  - [Search by image](#search-by-image)
  - [OpenRouter Backend](#openrouter-backend)
  - [Local Backend (no API key needed)](#local-backend-no-api-key-needed)
  - [Why the local model is fast](#why-the-local-model-is-fast)
  - [Tesla Metadata Overlay](#tesla-metadata-overlay)
  - [Redact with SentryBlur](#redact-with-sentryblur)
  - [Managing the index](#managing-the-index)
  - [Verbose mode](#verbose-mode)
- [How is this possible?](#how-is-this-possible)
- [Cost](#cost)
- [Known Warnings (harmless)](#known-warnings-harmless)
- [Limitations & Future Work](#limitations--future-work)
- [Compatibility](#compatibility)
- [Requirements](#requirements)

## How it works

SentrySearch splits your videos into overlapping chunks, embeds each chunk using Google's Gemini Embedding API, OpenRouter-backed Gemini vision captions, or a local Qwen3-VL model, and stores the vectors in a local ChromaDB database. When you search, your text query (or image, see [search by image](#search-by-image)) is embedded into the same vector space and matched against the stored video embeddings. The top match is automatically trimmed from the original file and saved as a clip.

## Getting Started

1. Install [uv](https://docs.astral.sh/uv/) (if you don't have it):

**macOS/Linux:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows:**
```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```


2. Clone and install:

```bash
git clone https://github.com/ssrajadh/sentrysearch.git
cd sentrysearch
uv tool install .
```

3. Set up your API key (or [use a local model instead](#local-backend-no-api-key-needed)):

```bash
sentrysearch init
```

This prompts for your Gemini API key, writes it to `.env`, and validates it with a test embedding.

4. Index your footage:

```bash
sentrysearch index /path/to/footage
```

5. Search:

```bash
sentrysearch search "red truck running a stop sign"
```

ffmpeg is required for video chunking and trimming. If you don't have it system-wide, the bundled `imageio-ffmpeg` is used automatically.

> **Manual setup:** If you prefer not to use `sentrysearch init`, you can copy `.env.example` to `.env` and add your key from [aistudio.google.com/apikey](https://aistudio.google.com/apikey) manually. For OpenRouter, set `OPENROUTER_API_KEY` and index with `--backend openrouter`.

## B-roll App Quick Start for Testers

This is the recommended flow when someone wants to clone this version, connect their own Google Drive or local footage folder, and use the browser UI for b-roll.

### What the tester gets

- A local browser app at `http://127.0.0.1:8765`
- Search over indexed video chunks using normal prompts like `hands typing laptop`
- Video previews with exact time ranges
- Tick/select clips manually
- `Generate Pack` exports only the selected time ranges, not full source videos
- `In Files` opens the output folder in File Explorer
- The **Library** section scans a video folder and indexes only new videos

### What stays local

The videos, Chroma DB, generated clips, previews, and CPU/storage work stay on the tester's computer. OpenRouter is only called when indexing new videos. Searching an already-indexed library is local.

### Requirements

Install these first:

- Git
- Python 3.11 or newer
- `uv`
- Google Drive for desktop if the videos live in Drive
- Optional: FFmpeg system install. The app has a Python ffmpeg fallback, but a normal FFmpeg install is still useful.

Install `uv` on Windows:

```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Close and reopen PowerShell after installing `uv`.

### Clone and install

Use the repo or branch that contains this b-roll UI work:

```powershell
git clone <YOUR_REPO_URL> sentrysearch-broll
cd sentrysearch-broll
uv sync
```

If you are giving this to a friend, push this project to your own repo first and send them that repo URL. The original upstream repo may not contain the b-roll UI additions yet.

### Add the OpenRouter key

Create this file:

```text
C:\Users\<your-windows-name>\.sentrysearch\.env
```

Put this inside it:

```text
OPENROUTER_API_KEY=your-openrouter-key-here
```

Do not commit this file. Do not send real API keys in chat.

The key is needed for indexing new videos. It is not needed just to search an already-indexed OpenRouter library.

### Connect Google Drive footage

Install Google Drive for desktop and sign in. Streaming mode is fine. The app only needs a local-looking folder path.

Examples:

```text
G:\My Drive\Broll Videos
G:\Shared drives\Creator Team\Broll
C:\Users\<name>\My Drive\Broll Videos
```

Copy the folder path that actually contains the `.mp4` or `.mov` files.

### Run the app

From the repo folder:

```powershell
uv run sentrysearch ui
```

Open:

```text
http://127.0.0.1:8765
```

### First run inside the UI

1. In **Library**, paste the Google Drive or local video folder path.
2. Click **Scan Folder**.
3. Confirm the count: videos found, already indexed, and new videos.
4. Click **Index New Videos**.
5. Wait for the log to finish. Failed files are logged and do not stop the whole library.
6. Search for b-roll with any prompt.
7. Tick the clips you want.
8. Click **Generate Selected Pack**.
9. Click **In Files** to open the exported clips.

The default local video folder is:

```text
drive_videos\library
```

So if a tester does not use Google Drive, they can put footage there and scan that folder.

### Day-to-day workflow

After the first index:

```powershell
cd sentrysearch-broll
uv run sentrysearch ui
```

Then in the browser:

1. Search normally.
2. Select clips.
3. Generate a pack.

When new videos are added to Drive:

1. Paste or keep the same Library folder.
2. Click **Scan Folder**.
3. Click **Index New Videos**.

The app skips already-indexed videos by filename/path, so refreshing the library is safe.

### Where files are saved

Generated selected packs go here by default:

```text
drive_videos\broll_packs_ui
```

Single saved clips go here:

```text
drive_videos\ui_saved
```

Index logs go here:

```text
drive_videos\index_logs
```

### Score colors

The score is a similarity score from search:

- Green: strong match
- Yellow: possible match
- Red: loose match

Use the video preview as the final judge. The score is a ranking hint, not a guarantee.

### Troubleshooting

If the UI says `No indexed footage found`, scan and index a library first.

If videos do not preview, the indexed file path is not available locally. Make sure Google Drive for desktop is running and the Library folder points at the right Drive folder.

If indexing asks for `OPENROUTER_API_KEY`, add it to `C:\Users\<name>\.sentrysearch\.env` and restart the UI.

If indexing is slow, that is normal for large videos. Google Drive may also stream the source file the first time it is read.

If disk space gets low, delete old generated clips from `drive_videos\broll_packs_ui` and `drive_videos\ui_saved`.

## Usage

### Init

```bash
$ sentrysearch init
Enter your Gemini API key (get one at https://aistudio.google.com/apikey): ****
Validating API key...
Setup complete. You're ready to go — run `sentrysearch index <directory>` to get started.
```

If a key is already configured, you'll be asked whether to overwrite it.

> **Tip:** Set a spending limit at [aistudio.google.com/billing](https://aistudio.google.com/billing) to prevent accidental overspending.

### Index footage

```bash
$ sentrysearch index /path/to/video/footage
Indexing file 1/3: front_2024-01-15_14-30.mp4 [chunk 1/4]
Indexing file 1/3: front_2024-01-15_14-30.mp4 [chunk 2/4]
...
Indexed 12 new chunks from 3 files. Total: 12 chunks from 3 files.
```

Options:

- `--chunk-duration 30` — seconds per chunk
- `--overlap 5` — overlap between chunks
- `--no-preprocess` — skip downscaling/frame rate reduction (send raw chunks)
- `--target-resolution 480` — target height in pixels for preprocessing
- `--target-fps 5` — target frame rate for preprocessing
- `--no-skip-still` — embed all chunks, even ones with no visual change
- `--backend openrouter` - use Gemini through OpenRouter for video captioning, then local text embeddings ([details below](#openrouter-backend))
- `--backend local` — use a local model instead of Gemini ([details below](#local-backend-no-api-key-needed))

### Search

```bash
$ sentrysearch search "red truck running a stop sign"
  #1 [0.87] front_2024-01-15_14-30.mp4 @ 02:15-02:45
  #2 [0.74] left_2024-01-15_14-30.mp4 @ 02:10-02:40
  #3 [0.61] front_2024-01-20_09-15.mp4 @ 00:30-01:00

Saved clip: ./match_front_2024-01-15_14-30_02m15s-02m45s.mp4
```

If the best result's similarity score is below the confidence threshold (default 0.41), you'll be prompted before trimming:

```
No confident match found (best score: 0.28). Show results anyway? [y/N]:
```

With `--no-trim`, low-confidence results are shown with a note instead of a prompt.

Options: `--results N`, `--output-dir DIR`, `--no-trim` to skip auto-trimming, `--threshold 0.5` to adjust the confidence cutoff, `--save-top N` to save the top N clips instead of just the best match. Backend and model are auto-detected from the index — pass `--backend` or `--model` only to override.

### B-roll

Use `broll` when you want several reusable clips for an edit:

```bash
$ sentrysearch broll "cinematic city traffic at night" --clips 5
  #1 [0.84] city_walk_001.mp4 @ 01:15-01:45
  #2 [0.80] skyline_003.mp4 @ 00:50-01:20
  ...

Saved clip: ~/sentrysearch_broll/match_city_walk_001_01m15s-01m45s.mp4
Saved clip: ~/sentrysearch_broll/match_skyline_003_00m50s-01m20s.mp4
```

By default, `broll` ranks 10 candidates and saves the top 5 clips into `~/sentrysearch_broll`. Use `--clips N` to change how many clips are saved, `--results N` to rank a wider candidate set, and the same backend/model flags as `search`.

Use `broll-pack` when you want editor-ready folders for multiple b-roll categories in one run:

```bash
$ sentrysearch broll-pack --clips 4 --output-dir ./broll_packs

[hands_typing_laptop] hands typing laptop
  saved 1: ./broll_packs/hands_typing_laptop/clip_01_...
  ...

[outdoor_night_interview] outdoor night interview
  saved 1: ./broll_packs/outdoor_night_interview/clip_01_...
  ...

Saved 28 clips across 7 categories.
Manifest: ./broll_packs/manifest.csv
```

Without `--prompt`, `broll-pack` uses a starter set of creator-friendly categories such as `hands typing laptop`, `people laughing indoors`, `outdoor night interview`, and `office presentation screen`. Pass repeated `--prompt "..."` flags or `--prompts-file prompts.txt` to make your own pack. It writes one folder per prompt plus a `manifest.csv` with source file, timestamp, score, and description. `--min-gap` avoids near-duplicate clips from the same source moment, and `--allow-cross-prompt-duplicates` lets categories reuse the same clip when you want overlap.

For rapid back-to-back b-roll pulls, keep the index and text embedder warm:

```bash
$ sentrysearch broll-shell --clips 5
Loading openrouter (google/gemini-2.5-flash)...
Ready. 90 chunks indexed. 5 clips/query. Type a b-roll prompt, :help for commands.
broll> coffee shop exterior morning
  #1 [0.82] cafe_001.mp4 @ 00:40-01:10
  #2 [0.78] street_004.mp4 @ 02:15-02:45
  saved: ~/sentrysearch_broll/match_cafe_001_00m40s-01m10s.mp4
  saved: ~/sentrysearch_broll/match_street_004_02m15s-02m45s.mp4
broll> hands pouring espresso close up
```

Inside `broll-shell`, use `:clips N`, `:n N`, `:open on|off`, `:help`, and `:quit`. This is the fastest workflow when you are trying a lot of short b-roll prompts in one editing session.

### Web UI

Start the local b-roll browser when you want to preview, save, and pack clips visually:

```bash
$ sentrysearch ui
SentrySearch UI running at http://127.0.0.1:8765
```

The UI searches the existing local index, streams matching source videos for preview, saves individual clips, and can generate a multi-category b-roll pack with a manifest. It also includes a **Library** section where you paste a local or Google Drive for desktop folder, scan for videos, and index only new files. Searches over an already-indexed OpenRouter library use local text embeddings; API calls are only needed when indexing new videos.

The search prompt is free-form: type whatever b-roll idea you want. The UI scans the indexed library first, then shows a preview of the most relevant clips. Tick the clips you want and generate a selected pack to export those exact time ranges.

### Portable index

You can ship a prebuilt Chroma index separately from the raw videos when you intentionally want a portable demo. Do not commit private indexes to a public repo; indexes can contain source filenames, timestamps, and generated descriptions. For normal friend testing, use the UI Library section and let each tester index their own Drive folder locally.

Set these optional environment variables before running the UI:

```bash
SENTRYSEARCH_DB_PATH=/path/to/shared/chroma-db
SENTRYSEARCH_LIBRARY_ROOT=/path/to/video/library
sentrysearch ui
```

`SENTRYSEARCH_DB_PATH` points at the shared Chroma DB folder. `SENTRYSEARCH_LIBRARY_ROOT` points at the local folder that contains the matching source videos. If the index was built on another machine, SentrySearch remaps missing indexed paths to files with the same names under that library root.

### Friend testing setup

For the cleanest friend test, have them clone the repo, add their own OpenRouter key, run the UI, paste their Google Drive for desktop folder into **Library**, and click **Index New Videos**. See [docs/FRIEND_SETUP.md](docs/FRIEND_SETUP.md) for the full setup guide and troubleshooting.

### Search by image

Use a reference image as the query — useful for "find clips that look like this" when describing the scene in words is awkward (a screenshot of a specific car, a reference frame from another video, etc.).

```bash
$ sentrysearch img ~/Downloads/image.jpg
  #1 [0.72] 2026-03-12_10-44-17-left_repeater.mp4 @ 00:00-00:30
  #2 [0.69] 2026-03-12_10-44-17-left_repeater.mp4 @ 00:25-00:55
  #3 [0.67] 2026-02-12_20-02-15-front.mp4 @ 00:00-00:18

Saved clip: ./match_2026-03-12_10-44-17-left_repeater_00m00s-00m30s.mp4
```

The image is embedded into the same vector space as the indexed video chunks and ranked by cosine similarity. All `search` flags are supported (`--results`, `--threshold`, `--save-top`, `--overlay`, `--no-trim`, `--backend`, `--model`).

Supported formats: JPG, PNG, WEBP, GIF, HEIC/HEIF on the Gemini backend; OpenRouter supports common web image formats such as JPG, PNG, and WEBP; the local backend additionally accepts anything PIL can decode (BMP, TIFF, etc.).

> **Note:** Image search returns *visually similar* matches, not necessarily the same object. A red sedan query may surface other red sedans of similar shape — calibrate expectations accordingly.

### OpenRouter Backend

Use this when you want Gemini through OpenRouter instead of a direct Gemini API key. SentrySearch samples frames from each video chunk, asks an OpenRouter Gemini vision model for short b-roll tags, and embeds those tags locally with Chroma's MiniLM text model.

Add the key to your stable config file:

```bash
OPENROUTER_API_KEY=your-openrouter-key
```

Then index and search:

```bash
sentrysearch index /path/to/footage --backend openrouter
sentrysearch broll "wide office exterior, people walking, daylight" --clips 5
```

The default OpenRouter model is `google/gemini-2.5-flash`. You can override it with a full OpenRouter model ID:

```bash
sentrysearch index /path/to/footage --backend openrouter --model google/gemini-2.5-flash
```

OpenRouter indexes are isolated from direct Gemini and local-model indexes, so vectors from different backends never mix.

### Local Backend (no API key needed)

Index and search using a local Qwen3-VL-Embedding model instead of the Gemini API. Free, private, and runs entirely on your machine. For the best search quality, use the Gemini backend — the local 8B model is a solid alternative when you need offline/private search, and the 2B model is a fallback when hardware can't support 8B.

The model is **auto-detected from your hardware** — qwen8b for NVIDIA GPUs and Macs with 24 GB+ RAM, qwen2b for smaller Macs and CPU-only systems. You can override with `--model qwen2b` or `--model qwen8b`. Pick an install based on your hardware:

| Hardware | Install command | Auto-detected model | Notes |
|---|---|---|---|
| **Apple Silicon, 24 GB+ RAM** | `uv tool install ".[local]"` | qwen8b | Full float16 via MPS |
| **Apple Silicon, 16 GB RAM** | `uv tool install ".[local]"` | qwen2b | 8B won't fit; 2B uses ~6 GB |
| **Apple Silicon, 8 GB RAM** | `uv tool install ".[local]"` | qwen2b | Tight — may swap under load; Gemini API recommended instead |
| **NVIDIA, 18 GB+ VRAM** | `uv tool install ".[local]"` | qwen8b | Full bf16 precision (CUDA wheels pulled automatically on Linux/Windows) |
| **NVIDIA, 8–16 GB VRAM** | `uv tool install ".[local-quantized]"` | qwen8b | 4-bit quantization (~6–8 GB) |

> **Won't work well:** Intel Macs and machines without a dedicated GPU. These fall back to CPU with float32 — too slow and memory-hungry for practical use. Use the **Gemini API backend** (the default) instead.

> **Not sure?** On Mac, use `".[local]"`. On NVIDIA, use `".[local-quantized]"` — 4-bit quantization works on the widest range of NVIDIA hardware with minimal quality loss. (bitsandbytes requires CUDA and does not work on Mac/MPS.)

**Mac prerequisite:** Install system FFmpeg (the local model's video processor requires it — the Gemini backend uses a bundled ffmpeg instead):

```bash
brew install ffmpeg
```

Index with `--backend local` and search — no extra flags needed:

```bash
sentrysearch index /path/to/footage --backend local
sentrysearch search "car running a red light"
```

The search command auto-detects the backend and model from whatever you indexed with. You can also use `--model` as a shorthand — it implies `--backend local`:

```bash
sentrysearch index /path/to/footage --model qwen2b   # same as --backend local --model qwen2b
sentrysearch search "car running a red light"          # auto-detects local/qwen2b from index
```

Options:
- `--model qwen2b` — smaller model, lower quality but only ~6 GB memory (also accepts full HuggingFace IDs)
- `--quantize` / `--no-quantize` — force 4-bit quantization on or off (default: auto-detect based on whether bitsandbytes is installed)

Notes:
- First run downloads the model (~16 GB for 8B, ~4 GB for 2B).
- Embeddings from different backends and models are **not compatible**. Each backend/model combination gets its own isolated index, so they can't accidentally mix. If you search with a model that has no indexed data, you'll be told which model was actually used.
- Speed varies by GPU core count — base M-series chips are slower than Pro/Max but produce identical results.

### Why the local model is fast

The local backend stays fast and memory-efficient through a few techniques that compound:

- **Preprocessing shrinks chunks before they hit the model.** Each 30s chunk is downscaled to 480p at 5fps via ffmpeg before embedding. A ~19 MB dashcam chunk becomes ~1 MB — a 95% reduction in pixels the model has to process. Model inference time scales with pixel count, not video duration, so this is the single biggest speedup.
- **Low frame sampling.** The video processor sends at most 32 frames per chunk to the model (`fps=1.0`, `max_frames=32`). A 30-second chunk produces ~30 frames — not hundreds.
- **MRL dimension truncation.** Qwen3-VL-Embedding supports [Matryoshka Representation Learning](https://arxiv.org/abs/2205.13147). Only the first 768 dimensions of each embedding are kept and L2-normalized, reducing storage and distance computation in ChromaDB.
- **Auto-quantization.** On NVIDIA GPUs with limited VRAM, the 8B model is automatically loaded in 4-bit (bitsandbytes) — dropping from ~18 GB to ~6-8 GB with minimal quality loss. A 4090 (24 GB) runs the full bf16 model with headroom to spare.
- **Still-frame skipping.** Chunks with no meaningful visual change (e.g. a parked car) are detected by comparing JPEG file sizes across sampled frames and skipped entirely — saving a full forward pass per chunk.

With all of this, expect ~2-5s per chunk on an A100 and ~3-8s on a T4. On a 4090, the 8B model in bf16 should be in the low single digits per chunk.

### Tesla Metadata Overlay

Burn speed, location, and time onto trimmed clips:

```bash
sentrysearch search "car cutting me off" --overlay
```

This extracts telemetry embedded in Tesla dashcam files (speed, GPS) and renders a HUD overlay. The overlay shows:

- **Top center:** speed and MPH label on a light gray card
- **Below card:** date and time (12-hour with AM/PM)
- **Top left:** city and road name (via reverse geocoding)

![tesla overlay](docs/tesla-overlay.png)

Requirements:

- Tesla firmware 2025.44.25 or later, HW3+
- SEI metadata is only present in driving footage (not parked/Sentry Mode)
- Reverse geocoding uses [OpenStreetMap's Nominatim API](https://nominatim.openstreetmap.org/) via geopy (optional)

Install with Tesla overlay support:

```bash
uv tool install ".[tesla]"
```

Without geopy, the overlay still works but omits the city/road name.

Source: [teslamotors/dashcam](https://github.com/teslamotors/dashcam)

### Redact with SentryBlur

[SentryBlur](https://github.com/ssrajadh/sentryblur) is a sibling tool for local face, license plate, and natural-language redaction of video. Every time `sentrysearch search` saves a clip, it caches the path to `~/.sentrysearch/last_clip.json`; SentryBlur picks that up via `--last`, so search-then-redact is two commands and no path-passing:

```bash
sentrysearch search "car cuts me off"
sentryblur prompt --last "road signs"   # → match_<...>_blurred.mp4
```

`sentryblur faces --last` and `sentryblur plates --last` work the same way. Pick `faces` or `plates` for fast CPU detectors; use `prompt "<text>"` for arbitrary objects (phone screens, monitors, name tags) — `prompt` requires an NVIDIA GPU or Apple Silicon. See the [SentryBlur README](https://github.com/ssrajadh/sentryblur#readme) for install instructions and hardware notes.

### Managing the index

```bash
# Show index info (files marked [missing] no longer exist on disk)
sentrysearch stats

# Remove specific files by path substring
sentrysearch remove path/to/footage

# Wipe the entire index
sentrysearch reset
```

### Verbose mode

Add `--verbose` to either command for debug info (embedding dimensions, API response times, similarity scores).

## How is this possible?

Both Gemini Embedding 2 and Qwen3-VL-Embedding can natively embed video — raw video pixels are projected into the same vector space as text queries. There's no transcription, no frame captioning, no text middleman. A text query like "red truck at a stop sign" is directly comparable to a 30-second video clip at the vector level. This is what makes sub-second semantic search over hours of footage practical.

## Cost

Indexing 1 hour of footage costs ~$2.84 with Gemini's embedding API (default settings: 30s chunks, 5s overlap):

> 1 hour = 3,600 seconds of video = 3,600 frames processed by the model.
> 3,600 frames × $0.00079 = ~$2.84/hr

The Gemini API natively extracts and tokenizes exactly 1 frame per second from uploaded video, regardless of the file's actual frame rate. The preprocessing step (which downscales chunks to 480p at 5fps via ffmpeg) is a local/bandwidth optimization — it keeps payload sizes small so API requests are fast and don't timeout — but does not change the number of frames the API processes.

Two built-in optimizations help reduce costs in different ways:

- **Preprocessing** (on by default) — chunks are downscaled to 480p at 5fps before uploading. Since the API processes at 1fps regardless, this only reduces upload size and transfer time, not the number of frames billed. It primarily improves speed and prevents request timeouts.
- **Still-frame skipping** (on by default) — chunks with no meaningful visual change (e.g. a parked car) are skipped entirely. This saves real API calls and directly reduces cost. The savings depend on your footage — Sentry Mode recordings with hours of idle time benefit the most, while action-packed driving footage may have nothing to skip.

Search queries are negligible (text embedding only).

Tuning options:

- `--chunk-duration` / `--overlap` — longer chunks with less overlap = fewer API calls = lower cost
- `--no-skip-still` — embed every chunk even if nothing is happening
- `--target-resolution` / `--target-fps` — adjust preprocessing quality
- `--no-preprocess` — send raw chunks to the API

## Known Warnings (harmless)

The local backend may print warnings during indexing and search. These are cosmetic and don't affect results:

- **`MPS: nonzero op is not natively supported`** — A known PyTorch limitation on Apple Silicon. The operation falls back to CPU for one step; everything else stays on the GPU. No impact on output quality.
- **`video_reader_backend torchcodec error, use torchvision as default`** — torchcodec can't find a compatible FFmpeg on macOS. The video processor falls back to torchvision automatically. This is expected and produces identical results.
- **`You are sending unauthenticated requests to the HF Hub`** — The model downloads from Hugging Face without a token. Download speeds may be slightly lower, but the model loads fine. Set a `HF_TOKEN` environment variable to silence this if it bothers you.

## Limitations & Future Work

- **Still-frame detection is heuristic** — it uses JPEG file size comparison across sampled frames. It may occasionally skip chunks with subtle motion or embed chunks that are truly static. Disable with `--no-skip-still` if you need every chunk indexed.
- **Search quality depends on chunk boundaries** — if an event spans two chunks, the overlapping window helps but isn't perfect. Smarter chunking (e.g. scene detection) could improve this.
- **Gemini Embedding 2 is in preview** — API behavior and pricing may change.

## Compatibility

This works with `.mp4` and `.mov` footage, not just Tesla Sentry Mode. The directory scanner recursively finds both file types regardless of folder structure.

## Requirements

- Python 3.11+
- `ffmpeg` on PATH, or use bundled ffmpeg via `imageio-ffmpeg` (installed by default)
- **Gemini backend:** Gemini API key ([get one free](https://aistudio.google.com/apikey))
- **Local backend:**
  - GPU with CUDA or Apple Metal (see [hardware table](#local-backend-no-api-key-needed) for VRAM/RAM requirements)
  - **macOS:** `brew install ffmpeg` (required by the video decoder)
  - **Linux/Windows:** no extra system dependencies
