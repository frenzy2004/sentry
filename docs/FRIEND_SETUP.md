# Friend setup guide

This guide is for testing the b-roll version of SentrySearch on another Windows machine.

## The short answer

Your friend can run the app locally and connect it to their own Google Drive for desktop folder.

Recommended setup:

1. Clone the repo.
2. Install with `uv sync`.
3. Add their own `OPENROUTER_API_KEY`.
4. Run `uv run sentrysearch ui`.
5. Paste their Google Drive video folder into the UI **Library** section.
6. Click **Scan Folder**.
7. Click **Index New Videos**.
8. Search, tick clips, and generate packs.

This uses their CPU, disk, and Drive mount. OpenRouter is only used while indexing new videos. Search and pack generation use the local index plus local source files.

## Requirements

Install these first:

- Git
- Python 3.11 or newer
- uv
- Google Drive for desktop if the footage is in Drive
- Optional but recommended: FFmpeg

Install uv on Windows:

```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

If `uv` is not found after installing, close and reopen PowerShell.

## Step 1: Clone and install

Use this repo:

```powershell
git clone https://github.com/frenzy2004/sentry.git sentrysearch-broll
cd sentrysearch-broll
uv sync
```

If `uv sync` fails on Windows with `invalid peer certificate: UnknownIssuer`, rerun it with system certificates:

```powershell
uv sync --system-certs
```

## Step 2: Add the OpenRouter key

Create this file:

```text
C:\Users\<name>\.sentrysearch\.env
```

Add:

```text
OPENROUTER_API_KEY=your-openrouter-key
```

Do not commit `.env` files and do not share real API keys in chat.

## Step 3: Find the video folder

Open File Explorer and find the folder that contains the videos.

Common Google Drive for desktop examples:

```text
G:\My Drive\Broll Videos
G:\Shared drives\Creator Team\Broll
C:\Users\<name>\My Drive\Broll Videos
```

Google Drive streaming mode is okay. The files look local to the app, and Drive downloads data as needed.

If the videos are not in Drive, put them in:

```text
drive_videos\library
```

or paste any local folder path into the UI.

## Step 4: Run the app

From the repo folder:

```powershell
uv run sentrysearch ui
```

If the same certificate issue appears while running commands, use:

```powershell
uv run --system-certs sentrysearch ui
```

Open:

```text
http://127.0.0.1:8765
```

## Step 5: Index videos from the UI

In the **Library** section:

1. Paste the video folder path.
2. Click **Scan Folder**.
3. Check the counts for videos found, already indexed, and new.
4. Click **Index New Videos**.
5. Wait for the log to finish.

The indexer skips files that are already indexed, so it is safe to scan/index again after adding new Drive videos.

Index logs are written to:

```text
drive_videos\index_logs
```

## Step 6: Make a b-roll pack

1. Type a prompt like `hands typing laptop`.
2. Click **Search**.
3. Preview the clips.
4. Tick/select the clips you want.
5. Click **Generate Selected Pack**.
6. Click **In Files** to open the output folder.

Generated selected packs are saved under:

```text
drive_videos\broll_packs_ui
```

Single saved clips are saved under:

```text
drive_videos\ui_saved
```

## If using Claude Code

Open Claude Code in the cloned repo folder and send this:

```text
I cloned https://github.com/frenzy2004/sentry.git. Please help me run the local SentrySearch b-roll UI.

Use this flow:
1. Check that Git, Python 3.11+, and uv are installed.
2. Run uv sync from the repo folder. If Windows shows `invalid peer certificate: UnknownIssuer`, run uv sync --system-certs.
3. Make sure C:\Users\<my-windows-name>\.sentrysearch\.env exists with OPENROUTER_API_KEY.
4. Run uv run sentrysearch ui. If the same certificate issue appears, run uv run --system-certs sentrysearch ui.
5. Open http://127.0.0.1:8765.
6. In the UI Library section, I will paste my Google Drive/local video folder, scan it, and index new videos.

Do not commit or print my API key. Do not upload my videos. Everything should stay local except OpenRouter calls during indexing.
```

If something fails, ask Claude Code to inspect:

```text
drive_videos\index_logs
```

## What calls the API

API calls happen when:

- indexing new videos with OpenRouter
- image search using OpenRouter

API calls do not happen when:

- searching an already-indexed library
- previewing source videos
- selecting clips
- generating packs from selected clips

## Optional portable index

You can share a Chroma index separately if you intentionally want a fast demo, but do not commit private indexes to a public repo. Indexes can contain source filenames, timestamps, and generated descriptions.

If you do share one privately, set:

```powershell
$env:SENTRYSEARCH_DB_PATH="C:\path\to\shared\db"
$env:SENTRYSEARCH_LIBRARY_ROOT="G:\My Drive\Broll Videos"
uv run sentrysearch ui
```

`SENTRYSEARCH_LIBRARY_ROOT` lets the app remap old indexed file paths to matching filenames under the tester's local Drive folder.

## Troubleshooting

### Search says `No indexed footage found`

Scan and index the video folder first.

### Videos do not play

The source video files are not being found locally. Make sure Google Drive for desktop is running and the Library folder points at the folder that actually contains the videos.

### Indexing asks for `OPENROUTER_API_KEY`

Add the key to:

```text
C:\Users\<name>\.sentrysearch\.env
```

Then restart the UI.

### Preview is slow

Google Drive may be streaming the video for the first time. For smoother testing, right-click the most important Drive folder and choose **Available offline**.

### Disk fills up

Generated packs can be large. Delete old generated clips from:

```text
drive_videos\broll_packs_ui
drive_videos\ui_saved
```

## What to send a tester

Send them:

- the repo link
- this guide
- the Drive folder they should point at
- their own OpenRouter key if they need to index new videos

Do not send `.env` files with real API keys.
