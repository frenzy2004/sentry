"""Tests for the local b-roll web UI helpers."""

import csv
import os
from unittest.mock import MagicMock, patch

import pytest

from sentrysearch.ui import BrollUIApp


def test_html_uses_simple_search_controls(tmp_path):
    html = BrollUIApp(tmp_path).html().decode("utf-8")
    assert "Matches to show" not in html
    assert "Backend" not in html
    assert "OpenRouter index" not in html
    assert "Gemini index" not in html
    assert "Local index" not in html
    assert "__DEFAULT_RESULTS__" not in html
    assert '<textarea id="prompts" readonly' in html
    assert "Selected clips" in html
    assert "select-toggle" in html
    assert "Select all shown" in html
    assert "Clear shown" in html
    assert "Select Clip</button>" not in html
    assert "In Files" in html
    assert "/api/open-folder" in html
    assert "Auto relevance floor" not in html
    assert "score-pill" in html
    assert "score-high" in html
    assert "score-mid" in html
    assert "score-low" in html
    assert "Library" in html
    assert "Scan Folder" in html
    assert "Index New Videos" in html
    assert "/api/library/scan" in html
    assert "/api/library/index" in html
    assert "Preset categories" in html
    assert "Prompt" in html
    assert "Generate Pack" in html


def test_scan_library_marks_new_and_existing_by_filename(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    existing = library / "existing.mp4"
    new = library / "new.mp4"
    existing.write_bytes(b"video")
    new.write_bytes(b"video")

    store = MagicMock()
    store.get_stats.return_value = {
        "total_chunks": 2,
        "unique_source_files": 1,
        "source_files": [str(tmp_path / "old_machine" / "existing.mp4")],
    }
    store.has_chunk.return_value = False

    with patch("sentrysearch.ui.detect_index",
               return_value=("openrouter", "google/gemini-2.5-flash")), \
         patch("sentrysearch.ui.SentryStore", return_value=store), \
         patch("sentrysearch.ui.scan_directory",
               return_value=[str(existing), str(new)]), \
         patch("sentrysearch.ui._get_video_duration", return_value=25.0), \
         patch("sentrysearch.ui.expected_chunk_spans",
               return_value=[(0.0, 25.0)]):
        data = BrollUIApp(tmp_path).scan_library(str(library))

    assert data["video_count"] == 2
    assert data["indexed_count"] == 1
    assert data["new_count"] == 1
    assert data["new_files"][0]["basename"] == "new.mp4"


def test_start_index_job_with_no_new_files_completes(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    app = BrollUIApp(tmp_path)
    scan = {
        "library_dir": str(library),
        "new_files": [],
        "video_count": 1,
        "indexed_count": 1,
        "new_count": 0,
    }

    with patch.object(app, "scan_library", return_value=scan):
        data = app.start_index_job({"library_dir": str(library)})

    assert data["status"] == "complete"
    assert data["total"] == 0
    assert "No new videos" in data["log_tail"]


def test_search_formats_results_with_media_urls(tmp_path):
    source = tmp_path / "drive_videos" / "library" / "clip.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"video")

    result = {
        "source_file": str(source),
        "start_time": 10.0,
        "end_time": 35.0,
        "similarity_score": 0.75,
        "description": "hands typing laptop",
    }

    store = MagicMock()
    store.get_stats.return_value = {
        "total_chunks": 1,
        "unique_source_files": 1,
        "source_files": [str(source)],
    }

    with patch("sentrysearch.ui.detect_index",
               return_value=("openrouter", "google/gemini-2.5-flash")), \
         patch("sentrysearch.ui.SentryStore", return_value=store), \
         patch("sentrysearch.ui.get_embedder", return_value=MagicMock()), \
         patch("sentrysearch.ui.search_footage", return_value=[result]):
        data = BrollUIApp(tmp_path).search("hands typing laptop", n_results=1)

    assert data["results"][0]["source_basename"] == "clip.mp4"
    assert "/media?path=" in data["results"][0]["media_url"]
    assert "#t=10.000,35.000" in data["results"][0]["media_url"]
    assert data["total_chunks"] == 1
    assert data["scanned_chunks"] == 1
    assert data["result_source_files"] == 1


def test_search_scans_full_small_library_before_showing_matches(tmp_path):
    source_a = tmp_path / "drive_videos" / "library" / "a.mp4"
    source_b = tmp_path / "drive_videos" / "library" / "b.mp4"
    source_a.parent.mkdir(parents=True)
    source_a.write_bytes(b"video")
    source_b.write_bytes(b"video")

    results = [
        {
            "source_file": str(source_a),
            "start_time": 0.0,
            "end_time": 20.0,
            "similarity_score": 0.9,
            "description": "best",
        },
        {
            "source_file": str(source_b),
            "start_time": 30.0,
            "end_time": 50.0,
            "similarity_score": 0.8,
            "description": "second",
        },
    ]

    store = MagicMock()
    store.get_stats.return_value = {
        "total_chunks": 12,
        "unique_source_files": 2,
        "source_files": [str(source_a), str(source_b)],
    }

    with patch("sentrysearch.ui.detect_index",
               return_value=("openrouter", "google/gemini-2.5-flash")), \
         patch("sentrysearch.ui.SentryStore", return_value=store), \
         patch("sentrysearch.ui.get_embedder", return_value=MagicMock()), \
         patch("sentrysearch.ui.search_footage", return_value=results) as search:
        data = BrollUIApp(tmp_path).search("hands typing laptop", n_results=1)

    assert search.call_args.kwargs["n_results"] == 12
    assert data["scanned_chunks"] == 12
    assert len(data["results"]) == 1


def test_save_clip_writes_under_default_save_dir(tmp_path):
    source = tmp_path / "drive_videos" / "library" / "clip.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"video")

    def fake_trim(source_file, start_time, end_time, output_path):
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(b"clip")
        return output_path

    app = BrollUIApp(tmp_path)
    result = {
        "source_file": str(source),
        "start_time": 10.0,
        "end_time": 35.0,
    }
    with patch("sentrysearch.ui.trim_clip", side_effect=fake_trim):
        saved = app.save_clip(result)

    assert saved["path"].endswith(".mp4")
    assert "drive_videos" in saved["path"]
    assert os.path.exists(saved["path"])


def test_open_folder_opens_allowed_output_folder(tmp_path):
    folder = tmp_path / "drive_videos" / "broll_packs_ui"
    folder.mkdir(parents=True)
    app = BrollUIApp(tmp_path)

    if os.name == "nt":
        patch_target = "sentrysearch.ui.os.startfile"
        patch_kwargs = {"create": True}
    else:
        patch_target = "sentrysearch.ui.subprocess.Popen"
        patch_kwargs = {}

    with patch(patch_target, **patch_kwargs) as opener:
        data = app.open_folder(str(folder))

    opener.assert_called_once()
    assert data == {"opened": True, "path": str(folder.resolve())}


def test_open_folder_rejects_missing_folder(tmp_path):
    app = BrollUIApp(tmp_path)

    with pytest.raises(PermissionError, match="allowed local output folder"):
        app.open_folder(tmp_path / "missing")


def test_generate_pack_writes_manifest(tmp_path):
    source = tmp_path / "drive_videos" / "library" / "clip.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"video")

    results = [
        {
            "source_file": str(source),
            "start_time": 0.0,
            "end_time": 25.0,
            "similarity_score": 0.8,
            "description": "office screen",
        },
        {
            "source_file": str(source),
            "start_time": 80.0,
            "end_time": 105.0,
            "similarity_score": 0.7,
            "description": "office screen",
        },
    ]

    def fake_trim(source_file, start_time, end_time, output_path):
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(b"clip")
        return output_path

    store = MagicMock()
    store.get_stats.return_value = {
        "total_chunks": 2,
        "unique_source_files": 1,
        "source_files": [str(source)],
    }
    out_dir = tmp_path / "packs"

    with patch("sentrysearch.ui.detect_index",
               return_value=("openrouter", "google/gemini-2.5-flash")), \
         patch("sentrysearch.ui.SentryStore", return_value=store), \
         patch("sentrysearch.ui.get_embedder", return_value=MagicMock()), \
         patch("sentrysearch.ui.search_footage", return_value=results), \
         patch("sentrysearch.ui.trim_clip", side_effect=fake_trim):
        data = BrollUIApp(tmp_path).generate_pack({
            "prompts": ["office screen"],
            "clips": 2,
            "results": 2,
            "output_dir": str(out_dir),
        })

    assert data["saved_count"] == 2
    assert data["failed_count"] == 0
    assert data["scanned_chunks"] == 2
    assert data["saved_source_files"] == 1
    assert len(data["clips"]) == 2
    assert data["clips"][0]["category"] == "office_screen"
    assert "/media?path=" in data["clips"][0]["media_url"]
    assert os.path.exists(data["manifest"])
    with open(data["manifest"], newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    assert rows[0]["category"] == "office_screen"


def test_generate_pack_from_selected_clips_trims_exact_ranges(tmp_path):
    source_a = tmp_path / "drive_videos" / "library" / "a.mp4"
    source_b = tmp_path / "drive_videos" / "library" / "b.mp4"
    source_a.parent.mkdir(parents=True)
    source_a.write_bytes(b"video")
    source_b.write_bytes(b"video")

    trim_calls = []

    def fake_trim(source_file, start_time, end_time, output_path, padding=2.0):
        trim_calls.append({
            "source_file": source_file,
            "start_time": start_time,
            "end_time": end_time,
            "output_path": output_path,
            "padding": padding,
        })
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(b"clip")
        return output_path

    out_dir = tmp_path / "packs"
    selected = [
        {
            "source_file": str(source_a),
            "source_basename": "a.mp4",
            "start_time": 460.0,
            "end_time": 485.0,
            "similarity_score": 0.81,
            "description": "talking head",
        },
        {
            "source_file": str(source_b),
            "source_basename": "b.mp4",
            "start_time": 40.0,
            "end_time": 65.0,
            "similarity_score": 0.73,
            "description": "gesturing",
        },
    ]

    with patch("sentrysearch.ui.search_footage") as search, \
         patch("sentrysearch.ui.trim_clip", side_effect=fake_trim):
        data = BrollUIApp(tmp_path).generate_pack({
            "selected_clips": selected,
            "selection_label": "talking head",
            "output_dir": str(out_dir),
        })

    search.assert_not_called()
    assert data["mode"] == "selected"
    assert data["saved_count"] == 2
    assert data["scanned_chunks"] == 0
    assert data["categories"][0]["category"] == "selected_talking_head"
    assert trim_calls[0]["source_file"] == str(source_a.resolve())
    assert trim_calls[0]["start_time"] == 460.0
    assert trim_calls[0]["end_time"] == 485.0
    assert trim_calls[0]["padding"] == 0.0
    assert "07m40s-08m05s" in trim_calls[0]["output_path"]
    assert "#t=" not in data["clips"][0]["media_url"]
    with open(data["manifest"], newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["start_time"] == "460.0"
    assert rows[0]["end_time"] == "485.0"


def test_generate_pack_without_clip_limit_saves_all_auto_relevant(tmp_path):
    source = tmp_path / "drive_videos" / "library" / "clip.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"video")

    results = [
        {
            "source_file": str(source),
            "start_time": 0.0,
            "end_time": 25.0,
            "similarity_score": 0.8,
            "description": "strong match",
        },
        {
            "source_file": str(source),
            "start_time": 30.0,
            "end_time": 55.0,
            "similarity_score": 0.7,
            "description": "also relevant",
        },
        {
            "source_file": str(source),
            "start_time": 60.0,
            "end_time": 85.0,
            "similarity_score": 0.2,
            "description": "weak match",
        },
    ]

    def fake_trim(source_file, start_time, end_time, output_path):
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(b"clip")
        return output_path

    store = MagicMock()
    store.get_stats.return_value = {
        "total_chunks": 3,
        "unique_source_files": 1,
        "source_files": [str(source)],
    }
    out_dir = tmp_path / "packs"

    with patch("sentrysearch.ui.detect_index",
               return_value=("openrouter", "google/gemini-2.5-flash")), \
         patch("sentrysearch.ui.SentryStore", return_value=store), \
         patch("sentrysearch.ui.get_embedder", return_value=MagicMock()), \
         patch("sentrysearch.ui.search_footage", return_value=results) as search, \
         patch("sentrysearch.ui.trim_clip", side_effect=fake_trim):
        data = BrollUIApp(tmp_path).generate_pack({
            "prompts": ["office screen"],
            "output_dir": str(out_dir),
        })

    assert search.call_args.kwargs["n_results"] == 3
    assert data["saved_count"] == 2
    assert data["failed_count"] == 0
    assert len(data["clips"]) == 2
    assert round(data["relevance_floor"], 2) == 0.60


def test_generate_pack_returns_partial_result_on_disk_full(tmp_path):
    source = tmp_path / "drive_videos" / "library" / "clip.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"video")

    result = {
        "source_file": str(source),
        "start_time": 0.0,
        "end_time": 25.0,
        "similarity_score": 0.8,
        "description": "office screen",
    }

    store = MagicMock()
    store.get_stats.return_value = {
        "total_chunks": 1,
        "unique_source_files": 1,
        "source_files": [str(source)],
    }
    out_dir = tmp_path / "packs"

    with patch("sentrysearch.ui.detect_index",
               return_value=("openrouter", "google/gemini-2.5-flash")), \
         patch("sentrysearch.ui.SentryStore", return_value=store), \
         patch("sentrysearch.ui.get_embedder", return_value=MagicMock()), \
         patch("sentrysearch.ui.search_footage", return_value=[result]), \
         patch("sentrysearch.ui.trim_clip",
               side_effect=RuntimeError("No space left on device")):
        data = BrollUIApp(tmp_path).generate_pack({
            "prompts": ["office screen"],
            "output_dir": str(out_dir),
        })

    assert data["saved_count"] == 0
    assert data["failed_count"] == 1
    assert "full" in data["stopped_reason"]
    assert os.path.exists(data["manifest"])
