"""OpenRouter-backed Gemini vision captions plus local text embeddings."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from .base_embedder import BaseEmbedder
from .chunker import _get_ffmpeg_executable
from .gemini_embedder import _install_system_truststore

load_dotenv(Path.home() / ".sentrysearch" / ".env")
load_dotenv()

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_OPENROUTER_MODEL = "google/gemini-2.5-flash"
TEXT_EMBEDDING_MODEL = "chroma/all-MiniLM-L6-v2"
DIMENSIONS = 384
DEFAULT_MAX_FRAMES = 6
DEFAULT_FRAME_HEIGHT = 360
MAX_CHAT_TOKENS = 96
MAX_DESCRIPTION_CHARS = 360

_VIDEO_PROMPT = (
    "B-roll tags. One line, max 30 words: subject, action, place, shot, "
    "lighting, objects, visible text. Keywords only. Omit unknowns."
)

_IMAGE_PROMPT = (
    "Image search tags. One line, max 30 words: subject, action, place, shot, "
    "lighting, colors, objects, visible text. Keywords only. Omit unknowns."
)


class OpenRouterAPIKeyError(RuntimeError):
    """Raised when OPENROUTER_API_KEY is missing or rejected."""


class OpenRouterQuotaError(RuntimeError):
    """Raised when OpenRouter refuses the request for quota/credits/rate limit."""


class OpenRouterError(RuntimeError):
    """Raised for non-auth OpenRouter request failures."""


def _short_error(body: str, limit: int = 500) -> str:
    """Return a compact API error string without flooding the terminal."""
    body = body.strip()
    if not body:
        return "empty response body"
    try:
        parsed = json.loads(body)
        error = parsed.get("error", parsed)
        if isinstance(error, dict):
            message = error.get("message") or error.get("detail") or str(error)
        else:
            message = str(error)
    except json.JSONDecodeError:
        message = body
    if len(message) > limit:
        message = message[: limit - 3] + "..."
    return message


def _compact_description(text: str, limit: int = MAX_DESCRIPTION_CHARS) -> str:
    """Normalize model captions into short, index-friendly text."""
    compact = " ".join(text.replace("\u2022", " ").split()).strip(" \"'")
    if "," in compact:
        noisy_tags = {
            "",
            "none",
            "n/a",
            "na",
            "unknown",
            "no text",
            "no visible text",
            "visible text none",
        }
        tags = []
        seen = set()
        for raw_tag in compact.split(","):
            tag = raw_tag.strip(" .;:\"'")
            normalized = tag.lower().replace(":", "").strip()
            if normalized in noisy_tags or normalized in seen:
                continue
            tags.append(tag)
            seen.add(normalized)
        compact = ", ".join(tags)
    if len(compact) <= limit:
        return compact
    compact = compact[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:")
    return compact or text[:limit].strip()


def _mime_type(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    if mime:
        return mime
    suffix = Path(path).suffix.lower()
    if suffix in (".jpg", ".jpeg"):
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    return "application/octet-stream"


class OpenRouterEmbedder(BaseEmbedder):
    """Gemini vision captioning through OpenRouter, indexed with local text vectors.

    OpenRouter exposes Gemini as a multimodal text-generation model, not as a
    Gemini embedding endpoint. To make it useful for retrieval, each video chunk
    is sampled into frames, Gemini writes a dense visual caption, and Chroma's
    local MiniLM embedder stores/searches those captions.
    """

    def __init__(
        self,
        model: str = DEFAULT_OPENROUTER_MODEL,
        *,
        max_frames: int = DEFAULT_MAX_FRAMES,
        frame_height: int = DEFAULT_FRAME_HEIGHT,
    ):
        _install_system_truststore()
        self._api_key = os.environ.get("OPENROUTER_API_KEY")
        self._model = model
        self._max_frames = max_frames
        self._frame_height = frame_height
        self._text_embedding_fn = None
        self.last_description: str | None = None

    def _post_chat(self, content: list[dict], *, verbose: bool = False) -> str:
        if not self._api_key:
            raise OpenRouterAPIKeyError(
                "OPENROUTER_API_KEY is not set.\n\n"
                "Existing OpenRouter indexes can still be searched locally, "
                "but indexing new videos or image queries need OpenRouter.\n\n"
                "Set it in ~/.sentrysearch/.env, for example:\n"
                "  OPENROUTER_API_KEY=your-key\n\n"
                "Then run with: sentrysearch index <directory> --backend openrouter"
            )
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.1,
            "max_tokens": MAX_CHAT_TOKENS,
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/ssrajadh/sentrysearch",
            "X-Title": "SentrySearch",
        }

        delay = 2.0
        for attempt in range(5):
            request = Request(OPENROUTER_API_URL, data=body, headers=headers, method="POST")
            try:
                with urlopen(request, timeout=120) as response:
                    data = response.read().decode("utf-8")
                parsed = json.loads(data)
                return _compact_description(
                    parsed["choices"][0]["message"]["content"],
                )
            except HTTPError as exc:
                status = exc.code
                error_body = exc.read().decode("utf-8", errors="replace")
                message = _short_error(error_body)
                if status in (401, 403):
                    raise OpenRouterAPIKeyError(
                        f"OpenRouter rejected OPENROUTER_API_KEY ({status}): {message}"
                    ) from exc
                if status == 402:
                    raise OpenRouterQuotaError(
                        "OpenRouter says this account needs credits or billing access "
                        f"for {self._model}: {message}"
                    ) from exc
                retryable = status in (408, 409, 429, 500, 502, 503, 504)
                if not retryable or attempt == 4:
                    if status == 429:
                        raise OpenRouterQuotaError(
                            f"OpenRouter rate limit exceeded for {self._model}: {message}"
                        ) from exc
                    raise OpenRouterError(
                        f"OpenRouter request failed ({status}) for {self._model}: {message}"
                    ) from exc
                if verbose:
                    print(
                        f"    [verbose] OpenRouter {status}, retrying in {delay:.0f}s: {message}",
                        file=sys.stderr,
                    )
                time.sleep(delay)
                delay = min(delay * 2, 30.0)
            except URLError as exc:
                if attempt == 4:
                    raise OpenRouterError(f"OpenRouter network error: {exc}") from exc
                if verbose:
                    print(
                        f"    [verbose] OpenRouter network error, retrying in {delay:.0f}s: {exc}",
                        file=sys.stderr,
                    )
                time.sleep(delay)
                delay = min(delay * 2, 30.0)

        raise OpenRouterError("OpenRouter request failed after retries.")

    def _get_text_embedding_fn(self):
        if self._text_embedding_fn is None:
            from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

            self._text_embedding_fn = DefaultEmbeddingFunction()
        return self._text_embedding_fn

    def _embed_text(self, text: str, *, verbose: bool = False) -> list[float]:
        t0 = time.monotonic()
        embedding = self._get_text_embedding_fn()([text])[0]
        result = [float(x) for x in embedding]
        if verbose:
            print(
                f"    [verbose] local text embedding dims={len(result)}, "
                f"time={time.monotonic() - t0:.2f}s",
                file=sys.stderr,
            )
        return result

    def _image_content(self, image_paths: list[str]) -> list[dict]:
        content: list[dict] = []
        for image_path in image_paths:
            with open(image_path, "rb") as f:
                encoded = base64.b64encode(f.read()).decode("ascii")
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{_mime_type(image_path)};base64,{encoded}",
                },
            })
        return content

    def _extract_frames(self, chunk_path: str, tmp_dir: str) -> list[str]:
        ffmpeg_exe = _get_ffmpeg_executable()
        out_pattern = os.path.join(tmp_dir, "frame_%03d.png")
        vf = f"fps=1/10,scale=-2:{self._frame_height},format=rgb24"

        def current_frames() -> list[str]:
            return sorted(
                os.path.join(tmp_dir, name)
                for name in os.listdir(tmp_dir)
                if name.lower().endswith(".png")
            )

        def extract_many(input_path: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [
                    ffmpeg_exe,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    input_path,
                    "-map",
                    "0:v:0",
                    "-vf",
                    vf,
                    "-frames:v",
                    str(self._max_frames),
                    out_pattern,
                ],
                capture_output=True,
                text=True,
            )

        def extract_one(input_path: str, output_path: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [
                    ffmpeg_exe,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-ss",
                    "0",
                    "-i",
                    input_path,
                    "-map",
                    "0:v:0",
                    "-frames:v",
                    "1",
                    "-vf",
                    f"scale=-2:{self._frame_height},format=rgb24",
                    output_path,
                ],
                capture_output=True,
                text=True,
            )

        def fix_color_metadata(input_path: str) -> str | None:
            fixed_path = os.path.join(tmp_dir, "fixed_color_metadata.mp4")
            fixed = subprocess.run(
                [
                    ffmpeg_exe,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    input_path,
                    "-map",
                    "0:v:0",
                    "-c",
                    "copy",
                    "-bsf:v",
                    "h264_metadata=colour_primaries=1:"
                    "transfer_characteristics=1:matrix_coefficients=1",
                    fixed_path,
                ],
                capture_output=True,
                text=True,
            )
            if fixed.returncode == 0 and os.path.isfile(fixed_path):
                return fixed_path
            return None

        result = extract_many(chunk_path)
        frames = current_frames()
        if result.returncode == 0 and frames:
            return frames

        fallback_path = os.path.join(tmp_dir, "frame_000.png")
        fallback = extract_one(chunk_path, fallback_path)
        if fallback.returncode == 0 and os.path.isfile(fallback_path):
            return [fallback_path]

        error_text = result.stderr or fallback.stderr
        if "Invalid color space" in error_text:
            fixed_path = fix_color_metadata(chunk_path)
            if fixed_path:
                for frame in current_frames():
                    os.remove(frame)
                result = extract_many(fixed_path)
                frames = current_frames()
                if result.returncode == 0 and frames:
                    return frames

                fallback_path = os.path.join(tmp_dir, "frame_000.png")
                fallback = extract_one(fixed_path, fallback_path)
                if fallback.returncode == 0 and os.path.isfile(fallback_path):
                    return [fallback_path]

        raise OpenRouterError(
            "Could not extract frames for OpenRouter indexing: "
            f"{result.stderr or fallback.stderr}"
        )

    def _caption_images(self, prompt: str, image_paths: list[str], *, verbose: bool) -> str:
        content = [{"type": "text", "text": prompt}]
        content.extend(self._image_content(image_paths))
        if verbose:
            total_kb = sum(os.path.getsize(p) for p in image_paths) / 1024
            print(
                f"    [verbose] sending {len(image_paths)} frame(s), "
                f"{total_kb:.0f}KB, to OpenRouter {self._model}",
                file=sys.stderr,
            )
        t0 = time.monotonic()
        description = self._post_chat(content, verbose=verbose)
        if verbose:
            print(
                f"    [verbose] OpenRouter caption time={time.monotonic() - t0:.2f}s",
                file=sys.stderr,
            )
            print(f"    [verbose] caption: {description}", file=sys.stderr)
        return description

    def embed_video_chunk(self, chunk_path: str, verbose: bool = False) -> list[float]:
        if not os.path.isfile(chunk_path):
            raise FileNotFoundError(f"Video chunk not found: {chunk_path}")
        with tempfile.TemporaryDirectory(prefix="sentrysearch_openrouter_") as tmp_dir:
            frames = self._extract_frames(chunk_path, tmp_dir)
            description = self._caption_images(_VIDEO_PROMPT, frames, verbose=verbose)
        self.last_description = description
        return self._embed_text(description, verbose=verbose)

    def embed_query(self, query_text: str, verbose: bool = False) -> list[float]:
        self.last_description = None
        return self._embed_text(query_text, verbose=verbose)

    def embed_image(self, image_path: str, verbose: bool = False) -> list[float]:
        if not os.path.isfile(image_path):
            raise FileNotFoundError(f"Image file not found: {image_path}")
        description = self._caption_images(_IMAGE_PROMPT, [image_path], verbose=verbose)
        self.last_description = description
        return self._embed_text(description, verbose=verbose)

    def dimensions(self) -> int:
        return DIMENSIONS
