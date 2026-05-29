"""Multimodal extraction and provider adapters.

The default path is conservative: collect media evidence, extract text from public subtitles, and
only call OCR/vision/ASR providers when explicit API settings are configured.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

from skillanything.config import Settings
from skillanything.connectors.http import fetch_bytes
from skillanything.models import CollectResult, MediaAsset, Segment
from skillanything.utils import stable_id, truncate


class MultimodalExtractor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def extract(self, result: CollectResult) -> list[Segment]:
        segments: list[Segment] = []
        seen: set[str] = set()
        subtitle_item_ids = {
            segment.item_id for segment in result.segments if "subtitle" in segment.source
        }
        for asset in result.assets[: self.settings.media_max_assets]:
            key = f"{asset.item_id}:{asset.kind}:{asset.url or asset.local_path}"
            if key in seen:
                continue
            seen.add(key)
            try:
                if asset.kind == "image":
                    segment = self._analyze_image(asset)
                    if segment:
                        segments.append(segment)
                elif asset.kind == "video":
                    if asset.item_id in subtitle_item_ids and not self.settings.vision_api_key:
                        continue
                    segments.extend(
                        self._analyze_video(
                            asset,
                            has_subtitle=asset.item_id in subtitle_item_ids,
                        )
                    )
                elif asset.kind == "audio":
                    segment = self._transcribe_audio(asset)
                    if segment:
                        segments.append(segment)
            except Exception as exc:
                segments.append(
                    Segment(
                        id=stable_id(asset.id, "multimodal-error", type(exc).__name__, str(exc)),
                        item_id=asset.item_id,
                        source="multimodal:error",
                        position=asset.metadata.get("position", asset.id),
                        text=f"{asset.kind} 分析失败：{type(exc).__name__}: {exc}",
                        metadata={"asset_id": asset.id, "asset_url": asset.url},
                    )
                )
        return segments

    def _analyze_image(self, asset: MediaAsset) -> Segment | None:
        if not asset.url and not asset.local_path:
            return None
        if self.settings.vision_api_key and self.settings.vision_base_url:
            text = OpenAICompatibleVision(self.settings).analyze_image(asset)
            source = "vision:openai_compatible"
        else:
            text = (
                "图片待 OCR/视觉分析。需要配置 SKILLANYTHING_VISION_BASE_URL、"
                "SKILLANYTHING_VISION_API_KEY、SKILLANYTHING_VISION_MODEL。"
            )
            source = "vision:pending"
        return Segment(
            id=stable_id(asset.id, source),
            item_id=asset.item_id,
            source=source,
            position=asset.metadata.get("position", asset.id),
            text=text,
            metadata={"asset_id": asset.id, "asset_url": asset.url},
        )

    def _analyze_video(self, asset: MediaAsset, has_subtitle: bool = False) -> list[Segment]:
        segments: list[Segment] = []
        if not has_subtitle and self.settings.asr_api_key and self.settings.asr_base_url:
            try:
                segment = self._transcribe_audio(asset)
                if segment:
                    segments.append(segment)
            except Exception:
                # Some videos are silent. Frame analysis should still proceed.
                pass
        if self.settings.vision_api_key and self.settings.vision_base_url:
            segments.extend(self._summarize_video_frames(asset))
        if not segments:
            segments.append(
                Segment(
                    id=stable_id(asset.id, "video:pending"),
                    item_id=asset.item_id,
                    source="video:pending",
                    position=asset.metadata.get("position", asset.id),
                    text=(
                        "视频待转写/抽帧分析。优先使用详情页字幕；如无字幕，需要配置 ASR "
                        "和视觉模型服务。"
                    ),
                    metadata={"asset_id": asset.id, "asset_url": asset.url},
                )
            )
        return segments

    def _summarize_video_frames(self, asset: MediaAsset) -> list[Segment]:
        frame_paths = _extract_frames(asset)
        segments: list[Segment] = []
        provider = OpenAICompatibleVision(self.settings)
        for index, frame in enumerate(frame_paths, start=1):
            text = provider.analyze_image(asset, local_path=frame)
            segments.append(
                Segment(
                    id=stable_id(asset.id, "frame", index, text),
                    item_id=asset.item_id,
                    source="vision:video_frame",
                    position=f"frame:{index}",
                    text=text,
                    metadata={"asset_id": asset.id, "frame": str(frame)},
                )
            )
        return segments

    def _transcribe_audio(self, asset: MediaAsset) -> Segment | None:
        if not self.settings.asr_api_key or not self.settings.asr_base_url:
            return None
        text = QwenASRFlash(self.settings).transcribe(asset)
        return Segment(
            id=stable_id(asset.id, "asr", text),
            item_id=asset.item_id,
            source="asr:qwen3_asr_flash",
            position=asset.metadata.get("position", asset.id),
            text=text,
            metadata={"asset_id": asset.id, "asset_url": asset.url},
        )


class OpenAICompatibleVision:
    """Vision adapter for DashScope/SiliconFlow/Volcengine OpenAI-compatible endpoints."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def analyze_image(self, asset: MediaAsset, local_path: Path | None = None) -> str:
        image_url = _image_payload_url(asset, local_path)
        prompt = (
            "请做研究素材级别的图片解析。提取所有可见文字、图表轴、数据指标、"
            "变量关系、推理链条、作者结论和可能的投资/宏观含义。"
            "输出中文，结构为：文字摘录、指标/工具、传导链、结论、备注。"
        )
        payload = {
            "model": self.settings.vision_model or "qwen-vl-max",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ],
            "temperature": 0.1,
        }
        data = _post_json(
            f"{self.settings.vision_base_url.rstrip('/')}/chat/completions",
            payload,
            self.settings.vision_api_key or "",
        )
        return _chat_text(data)


class QwenASRFlash:
    """Qwen3-ASR-Flash adapter through DashScope OpenAI-compatible chat completions."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def transcribe(self, asset: MediaAsset) -> str:
        texts: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            for index, audio_data in enumerate(
                _audio_payload_data_list(asset, Path(tmp)),
                start=1,
            ):
                asr_options: dict[str, Any] = {"enable_itn": False}
                if self.settings.asr_language:
                    asr_options["language"] = self.settings.asr_language
                payload = {
                    "model": self.settings.asr_model or "qwen3-asr-flash",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_audio",
                                    "input_audio": {"data": audio_data},
                                }
                            ],
                        }
                    ],
                    "stream": False,
                    "asr_options": asr_options,
                }
                base_url = (self.settings.asr_base_url or "").rstrip("/")
                data = _post_json(
                    f"{base_url}/chat/completions",
                    payload,
                    self.settings.asr_api_key or "",
                )
                text = _chat_text(data)
                texts.append(f"[part {index}]\n{text}" if len(texts) else text)
        return "\n\n".join(texts)


def _post_json(url: str, payload: dict[str, Any], api_key: str) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _chat_text(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(str(part.get("text", part)) for part in content)
    return truncate(json.dumps(data, ensure_ascii=False), 4000)


def _image_payload_url(asset: MediaAsset, local_path: Path | None) -> str:
    if local_path:
        data = local_path.read_bytes()
        encoded = base64.b64encode(data).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"
    if asset.local_path:
        path = Path(asset.local_path)
        if path.exists():
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            return f"data:image/jpeg;base64,{encoded}"
    if not asset.url:
        raise ValueError("image asset has neither url nor local_path")
    return asset.url


def _audio_payload_data_list(asset: MediaAsset, tmp_dir: Path) -> list[str]:
    source_path = Path(asset.local_path) if asset.local_path else None
    if asset.kind == "video":
        extracted = _extract_audio(asset)
        if extracted:
            source_path = extracted
    if source_path and source_path.exists():
        chunks = _split_audio(source_path, tmp_dir)
        if chunks:
            return [_file_data_uri(chunk, "audio/mpeg") for chunk in chunks]
        return [_file_data_uri(source_path)]
    if asset.url:
        return [asset.url]
    raise ValueError("audio/video asset has neither url nor local_path")


def _split_audio(source_path: Path, tmp_dir: Path, seconds: int = 120) -> list[Path]:
    ffmpeg = _ffmpeg_executable()
    if not ffmpeg:
        return []
    pattern = tmp_dir / "chunk-%03d.mp3"
    completed = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(source_path),
            "-vn",
            "-f",
            "segment",
            "-segment_time",
            str(seconds),
            "-reset_timestamps",
            "1",
            "-acodec",
            "libmp3lame",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(pattern),
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if completed.returncode != 0:
        return []
    return [path for path in sorted(tmp_dir.glob("chunk-*.mp3")) if path.stat().st_size > 0]


def _extract_audio(asset: MediaAsset) -> Path | None:
    ffmpeg = _ffmpeg_executable()
    if not ffmpeg:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        source = Path(asset.local_path) if asset.local_path else tmp_dir / "video.mp4"
        if not asset.local_path and asset.url:
            source.write_bytes(fetch_bytes(asset.url, timeout=120))
        audio = tmp_dir / "audio.mp3"
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(source),
                "-vn",
                "-acodec",
                "libmp3lame",
                "-ar",
                "16000",
                "-ac",
                "1",
                str(audio),
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if not audio.exists() or audio.stat().st_size == 0:
            return None
        audio_bytes = audio.read_bytes()
        final = Path(tempfile.gettempdir()) / f"skillanything-audio-{stable_id(audio_bytes)}.mp3"
        final.write_bytes(audio_bytes)
        return final


def _file_data_uri(path: Path, mime_type: str | None = None) -> str:
    mime = mime_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _extract_frames(asset: MediaAsset, count: int = 3) -> list[Path]:
    if not asset.url and not asset.local_path:
        return []
    ffmpeg = _ffmpeg_executable()
    if not ffmpeg:
        return []
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        source = Path(asset.local_path) if asset.local_path else tmp_dir / "video.mp4"
        if not asset.local_path and asset.url:
            source.write_bytes(fetch_bytes(asset.url, timeout=60))
        frame_pattern = tmp_dir / "frame-%03d.jpg"
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(source),
                "-vf",
                f"fps=1/{max(1, count)}",
                "-frames:v",
                str(count),
                str(frame_pattern),
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        persisted: list[Path] = []
        for frame in sorted(tmp_dir.glob("frame-*.jpg")):
            frame_bytes = frame.read_bytes()
            final = Path(tempfile.gettempdir()) / f"skillanything-{stable_id(frame_bytes)}.jpg"
            final.write_bytes(frame_bytes)
            persisted.append(final)
        return persisted


def _ffmpeg_executable() -> str | None:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return "ffmpeg"
    except OSError:
        return None
