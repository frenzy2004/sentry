"""Local web UI for browsing and exporting b-roll clips."""

from __future__ import annotations

import json
import mimetypes
import os
import subprocess
import re
import shutil
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from .chunker import (
    SUPPORTED_VIDEO_EXTENSIONS,
    _get_video_duration,
    expected_chunk_spans,
    scan_directory,
)
from .cli import (
    BROLL_PACK_DEFAULT_PROMPTS,
    _default_openrouter_model,
    _pack_clip_filename,
    _select_broll_pack_results,
    _slugify_prompt,
    _unique_slug,
    _write_broll_pack_manifest,
)
from .embedder import get_embedder, reset_embedder
from .local_embedder import normalize_model_key
from .search import search_footage
from .store import SentryStore, detect_index
from .trimmer import trim_clip


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_RESULTS = 24
DEFAULT_LIBRARY_DIR = "drive_videos\\library"
DEFAULT_INDEX_CHUNK_DURATION = 25
DEFAULT_INDEX_OVERLAP = 5
FULL_SCAN_CHUNK_LIMIT = 5000
AUTO_RELEVANCE_MIN_SCORE = 0.30
AUTO_RELEVANCE_RATIO = 0.75
AUTO_RELEVANCE_DROP = 0.20
MIN_FREE_BYTES = 256 * 1024 * 1024


HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SentrySearch B-roll</title>
  <style>
    :root {
      --bg: #f7f8fa;
      --panel: #ffffff;
      --ink: #18202a;
      --muted: #637083;
      --line: #d9e0e8;
      --accent: #0f766e;
      --accent-dark: #0b5f59;
      --amber: #b7791f;
      --danger: #b42318;
      --shadow: 0 8px 20px rgba(20, 32, 46, .08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }
    button, input, textarea, select {
      font: inherit;
      letter-spacing: 0;
    }
    .app {
      min-height: 100vh;
      display: grid;
      grid-template-columns: minmax(320px, 380px) 1fr;
    }
    aside {
      border-right: 1px solid var(--line);
      background: var(--panel);
      padding: 18px;
      overflow: auto;
    }
    main {
      padding: 18px;
      overflow: auto;
    }
    .brand {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 18px;
    }
    .brand h1 {
      margin: 0;
      font-size: 20px;
      line-height: 1.2;
    }
    .status {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.4;
    }
    .callout {
      margin: 0 0 16px;
      padding: 10px 11px;
      border: 1px solid #c8d7e2;
      border-radius: 6px;
      background: #f4f9fb;
      color: #2e455c;
      font-size: 13px;
      line-height: 1.45;
    }
    .section {
      border-top: 1px solid var(--line);
      padding-top: 16px;
      margin-top: 16px;
    }
    .section h2 {
      margin: 0 0 10px;
      font-size: 14px;
      line-height: 1.3;
      text-transform: uppercase;
      color: #3c4a5c;
    }
    label {
      display: block;
      margin: 10px 0 6px;
      font-size: 13px;
      color: #364456;
    }
    input, textarea, select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px 11px;
      background: #fff;
      color: var(--ink);
      min-width: 0;
    }
    textarea {
      min-height: 158px;
      resize: vertical;
    }
    textarea[readonly] {
      background: #f7f9fb;
      color: #4b5563;
      cursor: default;
    }
    .row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }
    .hint {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.4;
      margin-top: 6px;
    }
    .actions {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 12px;
    }
    button {
      border: 1px solid transparent;
      border-radius: 6px;
      padding: 9px 12px;
      cursor: pointer;
      background: #eef3f7;
      color: #213044;
      min-height: 38px;
    }
    button.primary {
      background: var(--accent);
      color: #fff;
    }
    button.primary:hover { background: var(--accent-dark); }
    button.ghost {
      background: #fff;
      border-color: var(--line);
    }
    button:disabled {
      opacity: .55;
      cursor: wait;
    }
    .summary {
      margin-top: 12px;
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfcfd;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
      white-space: pre-wrap;
    }
    .summary strong {
      color: var(--ink);
    }
    .summary.log {
      max-height: 190px;
      overflow: auto;
      font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
      font-size: 12px;
    }
    .toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 14px;
      flex-wrap: wrap;
    }
    .toolbar h2 {
      margin: 0;
      font-size: 18px;
    }
    .result-controls {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      flex-wrap: wrap;
      gap: 8px 12px;
    }
    .toolbar-actions {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .toolbar-actions button {
      min-height: 32px;
      padding: 6px 9px;
      font-size: 13px;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
      gap: 14px;
    }
    .clip {
      position: relative;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      box-shadow: var(--shadow);
    }
    .clip.selected {
      border-color: var(--accent);
      box-shadow: 0 0 0 2px rgba(15, 118, 110, .16), var(--shadow);
    }
    .media-wrap {
      position: relative;
      background: #111827;
    }
    .clip video {
      display: block;
      width: 100%;
      aspect-ratio: 16 / 9;
      background: #111827;
      object-fit: contain;
    }
    .select-toggle {
      position: absolute;
      top: 10px;
      right: 10px;
      z-index: 2;
      width: 34px;
      height: 34px;
      display: grid;
      place-items: center;
      border-radius: 999px;
      background: rgba(15, 23, 42, .68);
      border: 1px solid rgba(255, 255, 255, .54);
      cursor: pointer;
    }
    .select-toggle:hover {
      background: rgba(15, 118, 110, .92);
      border-color: rgba(255, 255, 255, .86);
    }
    .select-toggle input {
      position: absolute;
      inset: 0;
      opacity: 0;
      cursor: pointer;
    }
    .select-box {
      position: relative;
      width: 20px;
      height: 20px;
      border: 2px solid #fff;
      border-radius: 5px;
      background: rgba(255, 255, 255, .08);
    }
    .select-toggle input:checked + .select-box {
      background: var(--accent);
      border-color: #fff;
    }
    .select-toggle input:checked + .select-box::after {
      content: "";
      position: absolute;
      left: 5px;
      top: 1px;
      width: 6px;
      height: 11px;
      border: solid #fff;
      border-width: 0 2px 2px 0;
      transform: rotate(45deg);
    }
    .clip-body {
      padding: 12px;
    }
    .clip-title {
      font-size: 14px;
      font-weight: 650;
      line-height: 1.35;
      overflow-wrap: anywhere;
      margin-bottom: 8px;
    }
    .meta {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 8px;
    }
    .pill {
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 3px 7px;
      background: #fbfcfd;
    }
    .score-pill {
      font-weight: 650;
      border-color: transparent;
    }
    .score-high {
      background: #dcfce7;
      color: #166534;
    }
    .score-mid {
      background: #fef3c7;
      color: #92400e;
    }
    .score-low {
      background: #fee2e2;
      color: #991b1b;
    }
    .desc {
      min-height: 38px;
      color: #334155;
      font-size: 13px;
      line-height: 1.45;
      overflow-wrap: anywhere;
    }
    .empty {
      border: 1px dashed var(--line);
      border-radius: 8px;
      padding: 28px;
      background: #fff;
      color: var(--muted);
      text-align: center;
    }
    .pack-list {
      margin-top: 12px;
      display: grid;
      gap: 8px;
      font-size: 13px;
    }
    .pack-line {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 10px;
      align-items: center;
      padding: 9px 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
    }
    .path-actions {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-top: 8px;
    }
    .path-actions .hint {
      margin-top: 0;
      overflow-wrap: anywhere;
    }
    .line-actions {
      display: flex;
      align-items: center;
      gap: 8px;
      white-space: nowrap;
    }
    .in-files {
      min-height: 30px;
      padding: 5px 9px;
      font-size: 12px;
    }
    .pack-overview {
      grid-column: 1 / -1;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      padding: 12px;
    }
    .pack-overview h3 {
      margin: 0;
      font-size: 14px;
      line-height: 1.35;
    }
    .pack-card-label {
      color: var(--accent);
      font-size: 12px;
      font-weight: 650;
      margin-bottom: 6px;
      overflow-wrap: anywhere;
    }
    .selection-list {
      display: grid;
      gap: 8px;
      margin-top: 10px;
    }
    .selection-item {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      align-items: center;
      padding: 8px 9px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfcfd;
      font-size: 12px;
      line-height: 1.35;
    }
    .selection-item strong {
      display: block;
      color: #29384a;
      overflow-wrap: anywhere;
    }
    .selection-item button {
      min-height: 30px;
      padding: 5px 8px;
    }
    .warn { color: var(--amber); }
    .error { color: var(--danger); }
    @media (max-width: 880px) {
      .app { grid-template-columns: 1fr; }
      aside { border-right: 0; border-bottom: 1px solid var(--line); }
      main { padding-top: 14px; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside>
      <div class="brand">
        <h1>SentrySearch B-roll</h1>
        <div class="status" id="status">Loading...</div>
      </div>
      <div class="callout" id="scanNote">
        Search ranks the whole indexed library and returns the most relevant clips first. Repeated files are okay when they are the best matches.
      </div>

      <div class="section">
        <h2>Library</h2>
        <label for="libraryDir">Video folder</label>
        <input id="libraryDir" value="__DEFAULT_LIBRARY_DIR__" autocomplete="off">
        <div class="hint">Paste a local folder path, including a Google Drive for desktop folder. Scan first, then index only new videos.</div>
        <div class="actions">
          <button class="ghost" id="scanLibraryBtn">Scan Folder</button>
          <button class="primary" id="indexLibraryBtn">Index New Videos</button>
          <button class="ghost" id="openLibraryBtn">In Files</button>
        </div>
        <div class="summary" id="librarySummary">Ready to scan your video folder.</div>
      </div>

      <div class="section">
        <h2>Search</h2>
        <label for="query">Prompt</label>
        <input id="query" value="hands typing laptop" autocomplete="off">
        <div class="hint">This does not re-index or call the API. It scans indexed chunks from all source videos, then shows the best matches.</div>
        <div class="actions">
          <button class="primary" id="searchBtn">Search</button>
          <button class="ghost" id="clearBtn">Clear</button>
        </div>
      </div>

      <div class="section">
        <h2>Pack</h2>
        <label>Selected clips</label>
        <div class="hint" id="selectionSummary">No clips selected. Select clips from search results, or generate from preset categories.</div>
        <div class="selection-list" id="selectionList"></div>
        <div class="actions">
          <button class="ghost" id="clearSelectionBtn">Clear Selected</button>
        </div>
        <label for="prompts">Preset categories</label>
        <textarea id="prompts" readonly aria-readonly="true"></textarea>
        <div class="hint">These pack presets are fixed. Use Search for any custom prompt.</div>
        <div class="hint">If clips are selected, Generate Pack saves those exact time ranges. If none are selected, it scans the preset categories.</div>
        <label for="outputDir">Output folder</label>
        <input id="outputDir" value="drive_videos\\broll_packs_ui">
        <div class="actions">
          <button class="primary" id="packBtn">Generate Pack</button>
        </div>
        <div class="summary" id="packSummary">Ready.</div>
      </div>
    </aside>

    <main>
      <div class="toolbar">
        <h2 id="resultTitle">Search Results</h2>
        <div class="result-controls">
          <div class="status" id="resultMeta">No query yet.</div>
          <div class="toolbar-actions">
            <button class="ghost" id="selectShownBtn">Select all shown</button>
            <button class="ghost" id="clearShownBtn">Clear shown</button>
          </div>
        </div>
      </div>
      <div id="resultsGrid" class="grid">
        <div class="empty">Run a search to preview indexed footage.</div>
      </div>
    </main>
  </div>

  <script>
    const defaults = __DEFAULT_PROMPTS__;
    const previewLimit = __DEFAULT_RESULTS__;
    const state = { results: [], selected: [], libraryScan: null, indexTimer: null };

    const $ = (id) => document.getElementById(id);
    $("prompts").value = defaults.join("\n");

    function setBusy(button, busy) {
      button.disabled = busy;
      if (busy) {
        button.dataset.restoreText = button.textContent;
        button.textContent = "Working...";
      } else {
        button.textContent = button.dataset.restoreText || button.textContent;
        delete button.dataset.restoreText;
      }
    }

    function fmtTime(seconds) {
      const s = Math.max(0, Math.floor(seconds || 0));
      const m = Math.floor(s / 60);
      const r = s % 60;
      return `${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
    }

    function fmtBytes(bytes) {
      const value = Number(bytes || 0);
      if (value >= 1073741824) return `${(value / 1073741824).toFixed(1)} GB`;
      if (value >= 1048576) return `${(value / 1048576).toFixed(1)} MB`;
      return `${Math.round(value / 1024)} KB`;
    }

    function scoreClass(score) {
      const value = Number(score || 0);
      if (value >= 0.42) return "score-high";
      if (value >= 0.30) return "score-mid";
      return "score-low";
    }

    function scoreHint(score) {
      const value = Number(score || 0);
      if (value >= 0.42) return "Strong match";
      if (value >= 0.30) return "Possible match";
      return "Loose match";
    }

    function scorePill(score) {
      const value = Number(score || 0);
      return `<span class="pill score-pill ${scoreClass(value)}" title="${scoreHint(value)}">score ${value.toFixed(2)}</span>`;
    }

    function clipKey(r) {
      return `${r.source_file}|${Number(r.start_time).toFixed(3)}|${Number(r.end_time).toFixed(3)}`;
    }

    function selectedIndexFor(result) {
      const key = clipKey(result);
      return state.selected.findIndex((clip) => clipKey(clip) === key);
    }

    function isSelected(result) {
      return selectedIndexFor(result) !== -1;
    }

    function syncResultSelectionButtons() {
      const hasResults = state.results.length > 0;
      const visibleKeys = new Set(state.results.map(clipKey));
      const visibleSelected = state.selected.some((clip) => visibleKeys.has(clipKey(clip)));
      $("selectShownBtn").disabled = !hasResults;
      $("clearShownBtn").disabled = !visibleSelected;
    }

    function updateSelectionUI() {
      const count = state.selected.length;
      $("selectionSummary").textContent = count
        ? `${count} selected. Generate Pack will export only these exact time ranges.`
        : "No clips selected. Select clips from search results, or generate from preset categories.";
      $("clearSelectionBtn").disabled = count === 0;
      $("packBtn").textContent = count ? "Generate Selected Pack" : "Generate Pack";
      $("selectionList").innerHTML = state.selected.map((clip, i) => `
        <div class="selection-item">
          <div>
            <strong>${i + 1}. ${escapeHtml(clip.source_basename)}</strong>
            <span>${fmtTime(clip.start_time)}-${fmtTime(clip.end_time)}</span>
          </div>
          <button class="ghost" onclick="removeSelected(${i})">Remove</button>
        </div>
      `).join("");
      syncResultSelectionButtons();
    }

    function toggleSelect(index) {
      const result = state.results[index];
      const existing = selectedIndexFor(result);
      if (existing >= 0) {
        state.selected.splice(existing, 1);
      } else {
        state.selected.push(result);
      }
      updateSelectionUI();
      renderResults(state.results);
    }

    function removeSelected(index) {
      state.selected.splice(index, 1);
      updateSelectionUI();
      renderResults(state.results);
    }

    function clearSelection() {
      state.selected = [];
      updateSelectionUI();
      renderResults(state.results);
    }

    function selectAllShown() {
      for (const result of state.results) {
        if (!isSelected(result)) state.selected.push(result);
      }
      renderResults(state.results);
      updateSelectionUI();
    }

    function clearShown() {
      const visibleKeys = new Set(state.results.map(clipKey));
      state.selected = state.selected.filter((clip) => !visibleKeys.has(clipKey(clip)));
      renderResults(state.results);
      updateSelectionUI();
    }

    async function api(path, options = {}) {
      const res = await fetch(path, options);
      const text = await res.text();
      let data = {};
      if (text) {
        try { data = JSON.parse(text); } catch { data = { error: text }; }
      }
      if (!res.ok) throw new Error(data.error || res.statusText);
      return data;
    }

    function libraryDir() {
      return $("libraryDir").value.trim();
    }

    function renderLibraryScan(data) {
      state.libraryScan = data;
      const sampleNew = (data.new_files || [])
        .slice(0, 4)
        .map((item) => `- ${item.basename}`)
        .join("\n");
      $("librarySummary").classList.remove("error", "log");
      $("librarySummary").innerHTML =
        `<strong>${Number(data.video_count || 0)} videos found.</strong>\n` +
        `${Number(data.indexed_count || 0)} already indexed. ` +
        `${Number(data.new_count || 0)} new. ` +
        `${Number(data.error_count || 0)} need attention.\n` +
        (sampleNew ? `\nNew videos:\n${escapeHtml(sampleNew)}` : "\nNo new videos detected.");
    }

    async function scanLibrary() {
      const btn = $("scanLibraryBtn");
      setBusy(btn, true);
      try {
        const data = await api("/api/library/scan", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ library_dir: libraryDir() })
        });
        renderLibraryScan(data);
      } catch (err) {
        $("librarySummary").textContent = err.message;
        $("librarySummary").classList.add("error");
      } finally {
        setBusy(btn, false);
      }
    }

    function renderIndexStatus(data) {
      const running = data.status === "running";
      $("indexLibraryBtn").disabled = running;
      $("scanLibraryBtn").disabled = running;
      $("librarySummary").classList.toggle("log", Boolean(data.log_tail));
      $("librarySummary").classList.toggle("error", data.status === "failed");
      const header =
        data.status === "running"
          ? `Indexing ${Number(data.current || 0)}/${Number(data.total || 0)} videos...`
          : data.status === "complete"
            ? `Index complete: ${Number(data.succeeded || 0)} succeeded, ${Number(data.failed || 0)} failed.`
            : data.status === "failed"
              ? `Index failed: ${escapeHtml(data.error || "unknown error")}`
              : "Ready to scan your video folder.";
      $("librarySummary").innerHTML =
        `<strong>${header}</strong>\n` +
        (data.current_file ? `${escapeHtml(data.current_file)}\n` : "") +
        (data.log_tail ? `\n${escapeHtml(data.log_tail)}` : "");
      if (!running && state.indexTimer) {
        clearInterval(state.indexTimer);
        state.indexTimer = null;
        loadStats();
      }
    }

    async function pollIndexStatus() {
      try {
        const data = await api("/api/library/index");
        renderIndexStatus(data);
      } catch (err) {
        $("librarySummary").textContent = err.message;
        $("librarySummary").classList.add("error");
        if (state.indexTimer) {
          clearInterval(state.indexTimer);
          state.indexTimer = null;
        }
      }
    }

    async function indexLibrary() {
      const btn = $("indexLibraryBtn");
      let startedRunning = false;
      setBusy(btn, true);
      try {
        const data = await api("/api/library/index", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ library_dir: libraryDir() })
        });
        startedRunning = data.status === "running";
        renderIndexStatus(data);
        if (startedRunning) {
          if (state.indexTimer) clearInterval(state.indexTimer);
          state.indexTimer = setInterval(pollIndexStatus, 2000);
        }
      } catch (err) {
        $("librarySummary").textContent = err.message;
        $("librarySummary").classList.add("error");
      } finally {
        if (startedRunning) {
          btn.textContent = btn.dataset.restoreText || "Index New Videos";
          delete btn.dataset.restoreText;
          btn.disabled = true;
        } else {
          setBusy(btn, false);
        }
      }
    }

    async function openLibraryFolder() {
      const btn = $("openLibraryBtn");
      setBusy(btn, true);
      try {
        await api("/api/open-folder", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: libraryDir() })
        });
        btn.dataset.restoreText = "In Files";
        btn.textContent = "Opened";
        setTimeout(() => { btn.textContent = "In Files"; }, 1300);
      } catch (err) {
        $("librarySummary").textContent = err.message;
        $("librarySummary").classList.add("error");
      } finally {
        btn.disabled = false;
      }
    }

    async function loadStats() {
      try {
        const data = await api("/api/stats");
        $("status").textContent = `${data.total_chunks} chunks / ${data.source_files} videos`;
      } catch (err) {
        $("status").textContent = "Index unavailable";
        $("status").classList.add("error");
      }
    }

    function renderResults(results) {
      state.results = results;
      const grid = $("resultsGrid");
      if (!results.length) {
        grid.innerHTML = '<div class="empty">No matches found.</div>';
        syncResultSelectionButtons();
        return;
      }
      grid.innerHTML = results.map((r, i) => {
        const selected = isSelected(r);
        return `
        <article class="clip${selected ? " selected" : ""}">
          <div class="media-wrap">
            <video controls preload="metadata" src="${r.media_url}"></video>
            <label class="select-toggle" title="${selected ? "Unselect clip" : "Select clip"}">
              <input type="checkbox" aria-label="${selected ? "Unselect clip" : "Select clip"}" ${selected ? "checked" : ""} onchange="toggleSelect(${i})">
              <span class="select-box" aria-hidden="true"></span>
            </label>
          </div>
          <div class="clip-body">
            <div class="clip-title">${i + 1}. ${escapeHtml(r.source_basename)}</div>
            <div class="meta">
              <span class="pill">${fmtTime(r.start_time)}-${fmtTime(r.end_time)}</span>
              ${scorePill(r.similarity_score)}
            </div>
            <div class="desc">${escapeHtml(r.description || "No description")}</div>
            <div class="actions">
              <button class="primary" onclick="saveClip(${i}, this)">Save Clip</button>
              <button class="ghost" onclick="copyStamp(${i})">Copy Time</button>
            </div>
          </div>
        </article>
      `;
      }).join("");
      syncResultSelectionButtons();
    }

    function escapeHtml(value) {
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
    }

    function folderButton(path) {
      if (!path) return "";
      return `<button class="ghost in-files" data-folder="${escapeHtml(path)}" onclick="openFolderFromButton(this)">In Files</button>`;
    }

    async function openFolderFromButton(btn) {
      const label = btn.textContent;
      setBusy(btn, true);
      try {
        await api("/api/open-folder", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: btn.dataset.folder || "" })
        });
        btn.dataset.restoreText = label;
        btn.textContent = "Opened";
        setTimeout(() => { btn.textContent = label; }, 1300);
      } catch (err) {
        btn.textContent = "Can't open";
        btn.classList.add("error");
      } finally {
        btn.disabled = false;
      }
    }

    async function runSearch() {
      const btn = $("searchBtn");
      setBusy(btn, true);
      $("resultMeta").classList.remove("error");
      try {
        const q = $("query").value.trim();
        const n = String(previewLimit);
        const params = new URLSearchParams({ q, results: n });
        const data = await api(`/api/search?${params.toString()}`);
        $("resultTitle").textContent = q || "Search Results";
        const total = data.total_chunks ?? "all";
        const videoCount = data.result_source_files ?? data.source_files ?? 0;
        const libraryVideos = data.source_files ?? "all";
        const scanned = data.scanned_chunks ?? total;
        $("resultMeta").textContent =
          `Showing ${data.results.length} clips from ${videoCount} videos. Scanned ${scanned}/${total} chunks across ${libraryVideos} videos`;
        renderResults(data.results);
      } catch (err) {
        $("resultMeta").textContent = err.message;
        $("resultMeta").classList.add("error");
      } finally {
        setBusy(btn, false);
      }
    }

    async function saveClip(index, btn) {
      const result = state.results[index];
      setBusy(btn, true);
      try {
        const data = await api("/api/save", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ result })
        });
        btn.textContent = "Saved";
        const link = document.createElement("a");
        link.href = data.media_url;
        link.textContent = "Open saved clip";
        link.target = "_blank";
        link.className = "status";
        btn.parentElement.appendChild(link);
      } catch (err) {
        btn.textContent = "Save failed";
        btn.classList.add("error");
      } finally {
        btn.disabled = false;
      }
    }

    async function copyStamp(index) {
      const r = state.results[index];
      const text = `${r.source_basename} ${fmtTime(r.start_time)}-${fmtTime(r.end_time)}`;
      await navigator.clipboard.writeText(text);
    }

    function renderPack(data) {
      state.results = [];
      const grid = $("resultsGrid");
      const categories = data.categories || [];
      const clips = data.clips || [];
      const overview = `
        <section class="pack-overview">
          <h3>Saved ${data.saved_count} clips from ${data.saved_source_files || 0} videos</h3>
          <div class="hint">${data.mode === "selected" ? "Exported manually selected time ranges." : `Scanned ${data.scanned_chunks || "all"} chunks across ${data.library_source_files || "all"} indexed videos.`}</div>
          ${data.failed_count ? `<div class="hint warn">Skipped ${data.failed_count} clips. ${escapeHtml(data.stopped_reason || data.failures?.[0]?.error || "")}</div>` : ""}
          ${data.free_bytes !== undefined ? `<div class="hint">Free space after pack: ${fmtBytes(data.free_bytes)}</div>` : ""}
          <div class="path-actions">
            <div class="hint">${escapeHtml(data.output_dir || "")}</div>
            ${folderButton(data.output_dir)}
          </div>
          <div class="pack-list">
            ${categories.map(c => `
              <div class="pack-line">
                <span>${escapeHtml(c.category)}</span>
                <span class="line-actions">
                  <strong>${Number(c.saved || 0)} saved</strong>
                  ${folderButton(c.folder)}
                </span>
              </div>
            `).join("")}
          </div>
        </section>
      `;
      const clipCards = clips.map((c, i) => `
        <article class="clip">
          <video controls preload="metadata" src="${c.media_url}"></video>
          <div class="clip-body">
            <div class="pack-card-label">${escapeHtml(c.category)}</div>
            <div class="clip-title">${i + 1}. ${escapeHtml(c.source_basename)}</div>
            <div class="meta">
              <span class="pill">${fmtTime(c.start_time)}-${fmtTime(c.end_time)}</span>
              ${scorePill(c.similarity_score)}
            </div>
            <div class="desc">${escapeHtml(c.description || "No description")}</div>
          </div>
        </article>
      `).join("");
      grid.innerHTML = clips.length ? overview + clipCards : overview;
    }

    async function generatePack() {
      const btn = $("packBtn");
      setBusy(btn, true);
      $("packSummary").textContent = "Generating...";
      $("packSummary").classList.remove("error");
      try {
        const prompts = $("prompts").value.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
        const selectedClips = state.selected.map((clip) => ({ ...clip }));
        const data = await api("/api/pack", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            prompts,
            selected_clips: selectedClips,
            selection_label: $("query").value.trim() || "selected clips",
            output_dir: $("outputDir").value
          })
        });
        const packMode = data.mode === "selected" ? "selected clips" : "pack";
        $("packSummary").textContent =
          `Saved ${data.saved_count} ${packMode} from ${data.saved_source_files || 0} source videos.\n` +
          (data.failed_count ? `Skipped ${data.failed_count} clips. ${data.stopped_reason || data.failures?.[0]?.error || ""}\n` : "") +
          (data.mode === "selected" ? "Used manually selected time ranges.\n" : `Scanned ${data.scanned_chunks || "all"} chunks across ${data.library_source_files || "all"} indexed videos.\n`) +
          (data.free_bytes !== undefined ? `Free space after pack: ${fmtBytes(data.free_bytes)}.\n` : "") +
          `Manifest: ${data.manifest}`;
        renderPack(data);
        $("resultTitle").textContent = "Generated Pack";
        $("resultMeta").textContent =
          `${data.saved_count} playable clips from ${data.saved_source_files || 0} videos`;
      } catch (err) {
        $("packSummary").textContent = err.message;
        $("packSummary").classList.add("error");
      } finally {
        setBusy(btn, false);
      }
    }

    $("searchBtn").addEventListener("click", runSearch);
    $("query").addEventListener("keydown", (e) => {
      if (e.key === "Enter") runSearch();
    });
    $("clearBtn").addEventListener("click", () => {
      $("query").value = "";
      $("resultsGrid").innerHTML = '<div class="empty">Run a search to preview indexed footage.</div>';
      $("resultMeta").textContent = "No query yet.";
      $("resultMeta").classList.remove("error");
    });
    $("scanLibraryBtn").addEventListener("click", scanLibrary);
    $("indexLibraryBtn").addEventListener("click", indexLibrary);
    $("openLibraryBtn").addEventListener("click", openLibraryFolder);
    $("clearSelectionBtn").addEventListener("click", clearSelection);
    $("selectShownBtn").addEventListener("click", selectAllShown);
    $("clearShownBtn").addEventListener("click", clearShown);
    $("packBtn").addEventListener("click", generatePack);
    updateSelectionUI();
    loadStats();
  </script>
</body>
</html>"""


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value)!r} is not JSON serializable")


def _mime(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    if guessed:
        return guessed
    if path.suffix.lower() == ".mov":
        return "video/quicktime"
    return "application/octet-stream"


def _abs(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _time_for_filename(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes:02d}m{secs:02d}s"


def _source_file_count(stats: dict) -> int:
    if "unique_source_files" in stats:
        return int(stats["unique_source_files"])
    return len(stats.get("source_files", []))


def _scan_depth(total_chunks: int, requested: int,
                source_files: int) -> int:
    """Return how many chunks to rank before trimming UI results."""
    if total_chunks <= 0:
        return 0
    if total_chunks <= FULL_SCAN_CHUNK_LIMIT:
        return total_chunks
    return min(total_chunks, max(requested * 25, source_files * 8, 300))


def _prioritize_source_variety(
    results: list[dict],
    max_per_source: int = 1,
) -> list[dict]:
    """Order results so each source video gets a chance before repeats."""
    if max_per_source <= 0:
        return list(results)

    primary: list[dict] = []
    overflow: list[dict] = []
    counts: dict[str, int] = {}
    for result in results:
        source = str(result["source_file"])
        current = counts.get(source, 0)
        if current < max_per_source:
            primary.append(result)
            counts[source] = current + 1
        else:
            overflow.append(result)
    return primary + overflow


def _auto_relevance_floor(
    results: list[dict],
    threshold: float | None = None,
) -> float:
    """Return the score floor for saving all relevant pack matches."""
    if threshold is not None:
        return float(threshold)
    if not results:
        return 1.0
    best = float(results[0].get("similarity_score", 0.0))
    if best <= AUTO_RELEVANCE_MIN_SCORE:
        return best
    return max(
        AUTO_RELEVANCE_MIN_SCORE,
        best * AUTO_RELEVANCE_RATIO,
        best - AUTO_RELEVANCE_DROP,
    )


def _free_bytes(path: str | Path) -> int:
    """Return free bytes on the filesystem containing path."""
    target = _abs(path)
    probe = target if target.exists() else target.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return int(shutil.disk_usage(probe).free)


def _is_disk_full_error(error: BaseException) -> bool:
    message = str(error).lower()
    return (
        "no space left on device" in message
        or "disk full" in message
        or "not enough space" in message
        or "error code: -28" in message
    )


def _tail_text(path: str | Path, max_chars: int = 6000) -> str:
    """Return the end of a text log without loading huge files into memory."""
    log_path = Path(path)
    if not log_path.is_file():
        return ""
    with log_path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - max_chars))
        return f.read().decode("utf-8", errors="replace")


class BrollUIApp:
    """Application state and API operations for the local UI server."""

    def __init__(self, cwd: str | Path | None = None):
        self.cwd = _abs(cwd or Path.cwd())
        self.default_save_dir = self.cwd / "drive_videos" / "ui_saved"
        self.default_pack_dir = self.cwd / "drive_videos" / "broll_packs_ui"
        self.default_library_dir = self.cwd / DEFAULT_LIBRARY_DIR
        self._loaded_key: tuple[str, str | None, bool | None] | None = None
        self._lock = threading.RLock()
        self._job_lock = threading.RLock()
        self._index_job: dict[str, Any] = {"status": "idle"}
        self._index_thread: threading.Thread | None = None
        self._index_process: subprocess.Popen | None = None

    def html(self) -> bytes:
        default_prompts = json.dumps(list(BROLL_PACK_DEFAULT_PROMPTS))
        html = HTML.replace("__DEFAULT_PROMPTS__", default_prompts)
        html = html.replace("__DEFAULT_RESULTS__", str(DEFAULT_RESULTS))
        html = html.replace("__DEFAULT_LIBRARY_DIR__", DEFAULT_LIBRARY_DIR)
        return html.encode("utf-8")

    def resolve_backend(
        self,
        backend: str | None = None,
        model: str | None = None,
    ) -> tuple[str, str | None]:
        if model is not None and backend is None:
            backend = "local"
        if backend == "local" and model is not None:
            model = normalize_model_key(model)
        if backend is None:
            detected_backend, detected_model = detect_index()
            backend = detected_backend or "gemini"
            if model is None:
                model = detected_model
        elif backend == "local" and model is None:
            detected_backend, detected_model = detect_index()
            if detected_backend == "local":
                model = detected_model
        elif backend == "openrouter" and model is None:
            detected_backend, detected_model = detect_index()
            if detected_backend == "openrouter":
                model = detected_model
            if model is None:
                model = _default_openrouter_model()
        return backend, model

    def ensure_embedder(
        self,
        backend: str,
        model: str | None,
        quantize: bool | None = None,
    ) -> None:
        key = (backend, model, quantize)
        with self._lock:
            if self._loaded_key != key:
                reset_embedder()
                get_embedder(backend, model=model, quantize=quantize)
                self._loaded_key = key

    def stats(self) -> dict:
        with self._lock:
            backend, model = self.resolve_backend()
            store = SentryStore(backend=backend, model=model)
            stats = store.get_stats()
            return {
                "backend": backend,
                "model": model,
                "total_chunks": stats["total_chunks"],
                "source_files": stats["unique_source_files"],
                "default_prompts": list(BROLL_PACK_DEFAULT_PROMPTS),
            }

    def resolve_local_path(
        self,
        value: str | Path | None,
        default: Path,
    ) -> Path:
        raw = Path(str(value).strip()).expanduser() if value else default
        if not raw.is_absolute():
            raw = self.cwd / raw
        return raw.resolve()

    def scan_library(
        self,
        library_dir: str | Path | None = None,
        *,
        chunk_duration: int = DEFAULT_INDEX_CHUNK_DURATION,
        overlap: int = DEFAULT_INDEX_OVERLAP,
    ) -> dict:
        """Scan a folder and classify videos as indexed or new."""
        folder = self.resolve_local_path(library_dir, self.default_library_dir)
        if not folder.is_dir():
            raise FileNotFoundError(f"Video folder does not exist: {folder}")
        if overlap >= chunk_duration:
            raise ValueError("Overlap must be smaller than chunk duration.")

        with self._lock:
            backend, model = self.resolve_backend()
            if backend == "gemini" and detect_index() == (None, None):
                backend, model = "openrouter", _default_openrouter_model()
            store = SentryStore(backend=backend, model=model)
            stats = store.get_stats()
            indexed_paths = {
                str(_abs(source)).lower()
                for source in stats.get("source_files", [])
                if str(source)
            }
            indexed_names = {
                Path(source).name.lower()
                for source in stats.get("source_files", [])
                if str(source)
            }

            videos = [Path(path).resolve() for path in scan_directory(str(folder))]
            items: list[dict] = []
            for video in videos:
                expected_chunks = 0
                indexed_chunks = 0
                scan_error = ""
                try:
                    duration = _get_video_duration(str(video))
                    spans = expected_chunk_spans(
                        duration,
                        chunk_duration=chunk_duration,
                        overlap=overlap,
                    )
                    expected_chunks = len(spans)
                    indexed_chunks = sum(
                        1
                        for start, _ in spans
                        if store.has_chunk(store.make_chunk_id(str(video), start))
                    )
                except Exception as exc:
                    scan_error = str(exc).splitlines()[0]

                path_known = str(video).lower() in indexed_paths
                name_known = video.name.lower() in indexed_names
                fully_indexed = (
                    path_known
                    or name_known
                    or (
                        expected_chunks > 0
                        and indexed_chunks >= expected_chunks
                    )
                )
                status = "indexed" if fully_indexed else "new"
                if scan_error and not fully_indexed:
                    status = "new"
                items.append({
                    "path": str(video),
                    "basename": video.name,
                    "status": status,
                    "indexed": fully_indexed,
                    "expected_chunks": expected_chunks,
                    "indexed_chunks": expected_chunks if fully_indexed else indexed_chunks,
                    "error": scan_error,
                })

            new_files = [item for item in items if item["status"] == "new"]
            indexed = [item for item in items if item["status"] == "indexed"]
            errors = [item for item in items if item.get("error")]
            return {
                "library_dir": str(folder),
                "backend": backend,
                "model": model,
                "chunk_duration": chunk_duration,
                "overlap": overlap,
                "video_count": len(items),
                "indexed_count": len(indexed),
                "new_count": len(new_files),
                "error_count": len(errors),
                "videos": items,
                "new_files": new_files,
            }

    def start_index_job(self, payload: dict) -> dict:
        """Start background indexing for only the videos not in the index."""
        with self._job_lock:
            if (
                self._index_thread is not None
                and self._index_thread.is_alive()
            ):
                return self.index_status()

            chunk_duration = int(
                payload.get("chunk_duration") or DEFAULT_INDEX_CHUNK_DURATION
            )
            overlap = int(payload.get("overlap") or DEFAULT_INDEX_OVERLAP)
            scan = self.scan_library(
                payload.get("library_dir"),
                chunk_duration=chunk_duration,
                overlap=overlap,
            )
            files = [item["path"] for item in scan["new_files"]]
            log_dir = self.cwd / "drive_videos" / "index_logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            log_path = log_dir / f"ui_index_{stamp}.log"

            self._index_job = {
                "status": "complete" if not files else "running",
                "library_dir": scan["library_dir"],
                "total": len(files),
                "current": 0,
                "current_file": "",
                "succeeded": 0,
                "failed": 0,
                "error": "",
                "started_at": time.time(),
                "finished_at": time.time() if not files else None,
                "log_path": str(log_path),
                "scan": scan,
            }

            if not files:
                log_path.write_text(
                    "No new videos found. Nothing to index.\n",
                    encoding="utf-8",
                )
                return self.index_status()

            thread = threading.Thread(
                target=self._run_index_job,
                args=(files, log_path, chunk_duration, overlap),
                daemon=True,
            )
            self._index_thread = thread
            thread.start()
            return self.index_status()

    def _run_index_job(
        self,
        files: list[str],
        log_path: Path,
        chunk_duration: int,
        overlap: int,
    ) -> None:
        env = os.environ.copy()
        code = "from sentrysearch.cli import cli; cli()"
        succeeded = 0
        failed = 0
        try:
            for index, source_file in enumerate(files, 1):
                basename = os.path.basename(source_file)
                with self._job_lock:
                    self._index_job.update({
                        "status": "running",
                        "current": index,
                        "current_file": basename,
                        "succeeded": succeeded,
                        "failed": failed,
                    })

                command = [
                    sys.executable,
                    "-c",
                    code,
                    "index",
                    source_file,
                    "--backend",
                    "openrouter",
                    "--chunk-duration",
                    str(chunk_duration),
                    "--overlap",
                    str(overlap),
                ]
                with log_path.open("a", encoding="utf-8", errors="replace") as log:
                    log.write(
                        f"\n=== {index}/{len(files)} {basename} ===\n"
                    )
                    log.flush()
                    process = subprocess.Popen(
                        command,
                        cwd=str(self.cwd),
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        text=True,
                        env=env,
                    )
                    with self._job_lock:
                        self._index_process = process
                    return_code = process.wait()
                    self._index_process = None
                    if return_code == 0:
                        succeeded += 1
                        log.write(f"=== done: {basename} ===\n")
                    else:
                        failed += 1
                        log.write(
                            f"=== failed ({return_code}): {basename} ===\n"
                        )
                    log.flush()
                with self._job_lock:
                    self._index_job.update({
                        "succeeded": succeeded,
                        "failed": failed,
                    })
        except Exception as exc:
            with self._job_lock:
                self._index_job.update({
                    "status": "failed",
                    "error": str(exc),
                    "finished_at": time.time(),
                    "succeeded": succeeded,
                    "failed": failed,
                })
            return

        with self._job_lock:
            self._index_job.update({
                "status": "complete",
                "finished_at": time.time(),
                "succeeded": succeeded,
                "failed": failed,
                "current_file": "",
            })

    def index_status(self) -> dict:
        with self._job_lock:
            data = dict(self._index_job)
        log_path = data.get("log_path")
        if log_path:
            data["log_tail"] = _tail_text(log_path)
        else:
            data["log_tail"] = ""
        data.pop("scan", None)
        return data

    def media_url(self, path: str | Path, start: float | None = None,
                  end: float | None = None) -> str:
        url = f"/media?path={quote(str(_abs(path)))}"
        if start is not None and end is not None:
            url += f"#t={max(0.0, float(start)):.3f},{max(0.0, float(end)):.3f}"
        return url

    def format_result(self, result: dict) -> dict:
        source_file = str(_abs(result["source_file"]))
        return {
            "source_file": source_file,
            "source_basename": os.path.basename(source_file),
            "start_time": float(result["start_time"]),
            "end_time": float(result["end_time"]),
            "similarity_score": float(result["similarity_score"]),
            "description": result.get("description", ""),
            "media_url": self.media_url(
                source_file, result["start_time"], result["end_time"],
            ),
        }

    def search(
        self,
        query: str,
        n_results: int = DEFAULT_RESULTS,
        backend: str | None = None,
        model: str | None = None,
    ) -> dict:
        query = query.strip()
        if not query:
            return {
                "results": [],
                "backend": backend,
                "model": model,
                "total_chunks": 0,
            }
        with self._lock:
            backend, model = self.resolve_backend(backend, model)
            store = SentryStore(backend=backend, model=model)
            stats = store.get_stats()
            if stats["total_chunks"] == 0:
                raise RuntimeError("No indexed footage found.")
            total_chunks = int(stats["total_chunks"])
            source_files = _source_file_count(stats)
            scanned_chunks = _scan_depth(total_chunks, n_results, source_files)
            self.ensure_embedder(backend, model)
            candidates = search_footage(
                query, store, n_results=scanned_chunks,
            )
            results = candidates[:n_results]
            return {
                "query": query,
                "backend": backend,
                "model": model,
                "total_chunks": total_chunks,
                "scanned_chunks": scanned_chunks,
                "source_files": source_files,
                "result_source_files": len({
                    r["source_file"] for r in results
                }),
                "results": [self.format_result(r) for r in results],
            }

    def is_allowed_media_path(self, path: str | Path) -> bool:
        resolved = _abs(path)
        if not resolved.is_file():
            return False
        if resolved.suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS:
            return False
        try:
            resolved.relative_to(self.cwd / "drive_videos")
            return True
        except ValueError:
            pass
        backend, model = self.resolve_backend()
        store = SentryStore(backend=backend, model=model)
        sources = set(store.get_stats().get("source_files", []))
        return str(resolved) in sources

    def is_allowed_folder_path(self, path: str | Path) -> bool:
        resolved = _abs(path)
        if not resolved.is_dir():
            return False
        # The UI is local-only, and Drive for desktop folders may live outside
        # the user's home directory (for example G:\Shared drives\...).
        return True

    def open_folder(self, path: str | Path) -> dict:
        folder = self.resolve_local_path(path, self.cwd)
        if not self.is_allowed_folder_path(folder):
            raise PermissionError("Folder is not an allowed local output folder.")
        if os.name == "nt":
            os.startfile(str(folder))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(
                ["xdg-open", str(folder)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        return {"opened": True, "path": str(folder)}

    def save_clip(self, result: dict, output_dir: str | None = None) -> dict:
        source_file = _abs(result["source_file"])
        if not self.is_allowed_media_path(source_file):
            raise PermissionError("Media path is not part of this library.")
        out_dir = _abs(output_dir) if output_dir else self.default_save_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        base = re.sub(r"[^A-Za-z0-9_-]+", "_", source_file.stem).strip("_")
        start = _time_for_filename(float(result["start_time"]))
        end = _time_for_filename(float(result["end_time"]))
        output_path = out_dir / f"saved_{base}_{start}-{end}.mp4"
        clip_path = trim_clip(
            source_file=str(source_file),
            start_time=float(result["start_time"]),
            end_time=float(result["end_time"]),
            output_path=str(output_path),
        )
        return {
            "path": clip_path,
            "media_url": self.media_url(clip_path),
        }

    def generate_selected_pack(self, payload: dict) -> dict:
        selected_clips = [
            clip for clip in payload.get("selected_clips", [])
            if isinstance(clip, dict)
        ]
        if not selected_clips:
            raise RuntimeError("No selected clips to export.")

        output_dir = _abs(payload.get("output_dir") or self.default_pack_dir)
        prompt = str(payload.get("selection_label") or "selected clips").strip()
        slug = _slugify_prompt(prompt) or "selected_clips"
        if slug == "selected_clips":
            category = slug
        else:
            category = f"selected_{slug}"
        prompt_dir = output_dir / category

        with self._lock:
            output_dir.mkdir(parents=True, exist_ok=True)
            prompt_dir.mkdir(parents=True, exist_ok=True)

            manifest_rows: list[dict] = []
            generated_clips: list[dict] = []
            failed_clips: list[dict] = []
            stopped_reason: str | None = None

            for rank, raw in enumerate(selected_clips, 1):
                source_file = _abs(raw.get("source_file", ""))
                result = {
                    "source_file": str(source_file),
                    "start_time": float(raw["start_time"]),
                    "end_time": float(raw["end_time"]),
                    "similarity_score": float(raw.get("similarity_score", 1.0)),
                    "description": raw.get("description", ""),
                }
                if result["end_time"] <= result["start_time"]:
                    failed_clips.append({
                        "prompt": prompt,
                        "category": category,
                        "rank": rank,
                        "source_file": str(source_file),
                        "source_basename": os.path.basename(source_file),
                        "start_time": result["start_time"],
                        "end_time": result["end_time"],
                        "similarity_score": result["similarity_score"],
                        "error": "Selected clip has an invalid time range.",
                    })
                    continue
                if not self.is_allowed_media_path(source_file):
                    failed_clips.append({
                        "prompt": prompt,
                        "category": category,
                        "rank": rank,
                        "source_file": str(source_file),
                        "source_basename": os.path.basename(source_file),
                        "start_time": result["start_time"],
                        "end_time": result["end_time"],
                        "similarity_score": result["similarity_score"],
                        "error": "Source video is not part of this library.",
                    })
                    continue
                output_path = prompt_dir / _pack_clip_filename(rank, result)
                if _free_bytes(output_dir) < MIN_FREE_BYTES:
                    stopped_reason = (
                        "Stopped early because the output drive is almost full."
                    )
                    failed_clips.append({
                        "prompt": prompt,
                        "category": category,
                        "rank": rank,
                        "source_file": str(source_file),
                        "source_basename": os.path.basename(source_file),
                        "start_time": result["start_time"],
                        "end_time": result["end_time"],
                        "similarity_score": result["similarity_score"],
                        "error": stopped_reason,
                    })
                    break
                try:
                    clip_path = trim_clip(
                        source_file=str(source_file),
                        start_time=result["start_time"],
                        end_time=result["end_time"],
                        output_path=str(output_path),
                        padding=0.0,
                    )
                except Exception as exc:
                    if output_path.exists():
                        output_path.unlink(missing_ok=True)
                    error = str(exc).splitlines()[0]
                    failed_clips.append({
                        "prompt": prompt,
                        "category": category,
                        "rank": rank,
                        "source_file": str(source_file),
                        "source_basename": os.path.basename(source_file),
                        "start_time": result["start_time"],
                        "end_time": result["end_time"],
                        "similarity_score": result["similarity_score"],
                        "error": error,
                    })
                    if _is_disk_full_error(exc):
                        stopped_reason = (
                            "Stopped early because the output drive is full."
                        )
                        break
                    continue

                row = {
                    "prompt": prompt,
                    "category": category,
                    "rank": rank,
                    "output_file": clip_path,
                    "source_file": str(source_file),
                    "source_basename": os.path.basename(source_file),
                    "start_time": result["start_time"],
                    "end_time": result["end_time"],
                    "similarity_score": result["similarity_score"],
                    "description": result["description"],
                }
                manifest_rows.append(row)
                generated_clips.append({
                    "prompt": prompt,
                    "category": category,
                    "rank": rank,
                    "path": clip_path,
                    "media_url": self.media_url(clip_path),
                    "source_file": str(source_file),
                    "source_basename": os.path.basename(source_file),
                    "start_time": result["start_time"],
                    "end_time": result["end_time"],
                    "similarity_score": result["similarity_score"],
                    "description": result["description"],
                })

            manifest = _write_broll_pack_manifest(str(output_dir), manifest_rows)
            saved_source_files = len({
                row["source_file"] for row in manifest_rows
            })
            return {
                "mode": "selected",
                "output_dir": str(output_dir),
                "manifest": manifest,
                "saved_count": len(manifest_rows),
                "saved_source_files": saved_source_files,
                "failed_count": len(failed_clips),
                "failures": failed_clips[:20],
                "stopped_reason": stopped_reason,
                "scanned_chunks": 0,
                "library_source_files": None,
                "free_bytes": _free_bytes(output_dir),
                "relevance_floor": 0.0,
                "category_count": 1,
                "categories": [{
                    "prompt": prompt,
                    "category": category,
                    "saved": len(manifest_rows),
                    "source_videos": saved_source_files,
                    "relevance_floor": 0.0,
                    "folder": str(prompt_dir),
                }],
                "clips": generated_clips,
            }

    def generate_pack(self, payload: dict) -> dict:
        if payload.get("selected_clips"):
            return self.generate_selected_pack(payload)

        prompts = [
            str(p).strip()
            for p in payload.get("prompts", [])
            if str(p).strip()
        ] or list(BROLL_PACK_DEFAULT_PROMPTS)
        clips_value = payload.get("clips")
        clip_limit = (
            None
            if clips_value in (None, "", "all")
            else max(1, int(clips_value))
        )
        requested = int(payload.get("results", 0) or 0)
        max_per_source = max(0, int(payload.get("max_per_source", 0)))
        min_gap = float(payload.get("min_gap", 0.0))
        threshold_value = payload.get("threshold")
        threshold = (
            None
            if threshold_value in (None, "", "auto")
            else float(threshold_value)
        )
        output_dir = _abs(payload.get("output_dir") or self.default_pack_dir)
        backend, model = self.resolve_backend(payload.get("backend"), payload.get("model"))

        with self._lock:
            store = SentryStore(backend=backend, model=model)
            stats = store.get_stats()
            if stats["total_chunks"] == 0:
                raise RuntimeError("No indexed footage found.")
            total_chunks = int(stats["total_chunks"])
            source_files = _source_file_count(stats)
            scan_request = requested or total_chunks
            scanned_chunks = _scan_depth(total_chunks, scan_request, source_files)
            self.ensure_embedder(backend, model)
            output_dir.mkdir(parents=True, exist_ok=True)

            manifest_rows: list[dict] = []
            categories: list[dict] = []
            generated_clips: list[dict] = []
            failed_clips: list[dict] = []
            used_slugs: set[str] = set()
            taken: list[dict] = []
            relevance_floors: list[float] = []
            stopped_reason: str | None = None

            for prompt in prompts:
                slug = _unique_slug(_slugify_prompt(prompt), used_slugs)
                prompt_dir = output_dir / slug
                prompt_dir.mkdir(parents=True, exist_ok=True)
                results = search_footage(
                    prompt, store, n_results=scanned_chunks,
                )
                results = _prioritize_source_variety(
                    results, max_per_source=max_per_source,
                )
                relevance_floor = _auto_relevance_floor(results, threshold)
                relevance_floors.append(relevance_floor)
                selected = _select_broll_pack_results(
                    results,
                    clips=clip_limit or len(results),
                    threshold=relevance_floor,
                    min_gap=min_gap,
                    taken=taken,
                )
                saved = 0
                for rank, result in enumerate(selected, 1):
                    output_path = prompt_dir / _pack_clip_filename(rank, result)
                    if _free_bytes(output_dir) < MIN_FREE_BYTES:
                        stopped_reason = (
                            "Stopped early because the output drive is almost full."
                        )
                        failed_clips.append({
                            "prompt": prompt,
                            "category": slug,
                            "rank": rank,
                            "source_file": result["source_file"],
                            "source_basename": os.path.basename(result["source_file"]),
                            "start_time": float(result["start_time"]),
                            "end_time": float(result["end_time"]),
                            "similarity_score": float(result["similarity_score"]),
                            "error": stopped_reason,
                        })
                        break
                    try:
                        clip_path = trim_clip(
                            source_file=result["source_file"],
                            start_time=result["start_time"],
                            end_time=result["end_time"],
                            output_path=str(output_path),
                        )
                    except Exception as exc:
                        if output_path.exists():
                            output_path.unlink(missing_ok=True)
                        error = str(exc).splitlines()[0]
                        failed_clips.append({
                            "prompt": prompt,
                            "category": slug,
                            "rank": rank,
                            "source_file": result["source_file"],
                            "source_basename": os.path.basename(result["source_file"]),
                            "start_time": float(result["start_time"]),
                            "end_time": float(result["end_time"]),
                            "similarity_score": float(result["similarity_score"]),
                            "error": error,
                        })
                        if _is_disk_full_error(exc):
                            stopped_reason = (
                                "Stopped early because the output drive is full."
                            )
                            break
                        continue
                    saved += 1
                    taken.append(result)
                    manifest_rows.append({
                        "prompt": prompt,
                        "category": slug,
                        "rank": rank,
                        "output_file": clip_path,
                        "source_file": result["source_file"],
                        "source_basename": os.path.basename(result["source_file"]),
                        "start_time": float(result["start_time"]),
                        "end_time": float(result["end_time"]),
                        "similarity_score": float(result["similarity_score"]),
                        "description": result.get("description", ""),
                    })
                    generated_clips.append({
                        "prompt": prompt,
                        "category": slug,
                        "rank": rank,
                        "path": clip_path,
                        "media_url": self.media_url(clip_path),
                        "source_file": result["source_file"],
                        "source_basename": os.path.basename(result["source_file"]),
                        "start_time": float(result["start_time"]),
                        "end_time": float(result["end_time"]),
                        "similarity_score": float(result["similarity_score"]),
                        "description": result.get("description", ""),
                    })
                categories.append({
                    "prompt": prompt,
                    "category": slug,
                    "saved": saved,
                    "source_videos": len({
                        r["source_file"] for r in selected
                    }),
                    "relevance_floor": relevance_floor,
                    "folder": str(prompt_dir),
                })
                if stopped_reason:
                    break

            manifest = _write_broll_pack_manifest(str(output_dir), manifest_rows)
            saved_source_files = len({
                row["source_file"] for row in manifest_rows
            })
            relevance_floor = min(relevance_floors) if relevance_floors else 0.0
            return {
                "mode": "search",
                "output_dir": str(output_dir),
                "manifest": manifest,
                "saved_count": len(manifest_rows),
                "saved_source_files": saved_source_files,
                "failed_count": len(failed_clips),
                "failures": failed_clips[:20],
                "stopped_reason": stopped_reason,
                "scanned_chunks": scanned_chunks,
                "library_source_files": source_files,
                "free_bytes": _free_bytes(output_dir),
                "relevance_floor": relevance_floor,
                "category_count": len(prompts),
                "categories": categories,
                "clips": generated_clips,
            }


class BrollUIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the local b-roll UI."""

    server: "BrollUIServer"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    @property
    def app(self) -> BrollUIApp:
        return self.server.app

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/":
                self._send_bytes(self.app.html(), "text/html; charset=utf-8")
            elif parsed.path == "/api/stats":
                self._send_json(self.app.stats())
            elif parsed.path == "/api/search":
                qs = parse_qs(parsed.query)
                query = qs.get("q", [""])[0]
                n_results = int(qs.get("results", [str(DEFAULT_RESULTS)])[0])
                backend = qs.get("backend", [None])[0] or None
                model = qs.get("model", [None])[0] or None
                self._send_json(self.app.search(query, n_results, backend, model))
            elif parsed.path == "/api/library/index":
                self._send_json(self.app.index_status())
            elif parsed.path == "/media":
                qs = parse_qs(parsed.query)
                raw_path = unquote(qs.get("path", [""])[0])
                self._send_media(raw_path)
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=500)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            payload = self._read_json()
            if parsed.path == "/api/save":
                self._send_json(
                    self.app.save_clip(
                        payload["result"],
                        output_dir=payload.get("output_dir"),
                    )
                )
            elif parsed.path == "/api/pack":
                self._send_json(self.app.generate_pack(payload))
            elif parsed.path == "/api/open-folder":
                self._send_json(self.app.open_folder(payload.get("path", "")))
            elif parsed.path == "/api/library/scan":
                self._send_json(
                    self.app.scan_library(payload.get("library_dir"))
                )
            elif parsed.path == "/api/library/index":
                self._send_json(self.app.start_index_job(payload))
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=500)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        data = self.rfile.read(length) if length else b"{}"
        return json.loads(data.decode("utf-8"))

    def _send_json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload, default=_json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_bytes(self, data: bytes, content_type: str,
                    status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_media(self, path: str) -> None:
        resolved = _abs(path)
        if not self.app.is_allowed_media_path(resolved):
            self.send_error(HTTPStatus.FORBIDDEN)
            return

        size = resolved.stat().st_size
        range_header = self.headers.get("Range")
        start = 0
        end = size - 1
        status = HTTPStatus.OK
        if range_header:
            match = re.match(r"bytes=(\d*)-(\d*)", range_header)
            if match:
                if match.group(1):
                    start = int(match.group(1))
                if match.group(2):
                    end = int(match.group(2))
                end = min(end, size - 1)
                if start > end:
                    self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    return
                status = HTTPStatus.PARTIAL_CONTENT

        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", _mime(resolved))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()

        with resolved.open("rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(1024 * 512, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)


class BrollUIServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], app: BrollUIApp):
        self.app = app
        super().__init__(address, BrollUIHandler)


def serve(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    *,
    open_browser: bool = False,
    cwd: str | Path | None = None,
) -> str:
    """Start the local UI server and block until interrupted."""
    app = BrollUIApp(cwd=cwd)
    server = BrollUIServer((host, port), app)
    url = f"http://{host}:{server.server_port}"
    if open_browser:
        webbrowser.open(url)
    print(f"SentrySearch UI running at {url}", flush=True)
    try:
        server.serve_forever()
    finally:
        reset_embedder()
    return url
