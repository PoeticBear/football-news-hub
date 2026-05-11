from __future__ import annotations

import os
from pathlib import Path

import httpx
from loguru import logger


class TTSGenerator:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.minimaxi.com/v1",
        model: str = "speech-2.8-hd",
        voice_id: str = "moss_audio_ce44fc67-7ce3-11f0-8de5-96e35d26fb85",
    ) -> None:
        self.api_key = api_key or os.environ.get("MINIMAX_API_KEY", "")
        self.base_url = base_url
        self.model = model
        self.voice_id = voice_id

    def generate_audio(
        self,
        text: str,
        output_path: str | Path,
        speed: float = 1.0,
        emotion: str = "calm",
    ) -> Path:
        if not self.api_key:
            raise ValueError("MINIMAX_API_KEY is not set")

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        chunks = self._split_text(text)
        logger.info(f"TTS: generating audio for {len(chunks)} chunk(s)")

        if len(chunks) == 1:
            audio_bytes = self._synthesize(chunks[0], speed=speed, emotion=emotion)
        else:
            audio_parts = []
            for i, chunk in enumerate(chunks):
                logger.info(f"TTS: synthesizing chunk {i + 1}/{len(chunks)} ({len(chunk)} chars)")
                part = self._synthesize(chunk, speed=speed, emotion=emotion)
                audio_parts.append(part)
            audio_bytes = b"".join(audio_parts)

        with open(output_path, "wb") as f:
            f.write(audio_bytes)

        logger.info(f"TTS: audio saved to {output_path} ({len(audio_bytes)} bytes)")
        return output_path

    def _synthesize(self, text: str, speed: float = 1.0, emotion: str = "calm") -> bytes:
        payload = {
            "model": self.model,
            "text": text,
            "stream": False,
            "voice_setting": {
                "voice_id": self.voice_id,
                "speed": speed,
                "vol": 1.0,
                "pitch": 0,
                "emotion": emotion,
            },
            "audio_setting": {
                "sample_rate": 32000,
                "bitrate": 128000,
                "format": "mp3",
                "channel": 1,
            },
            "output_format": "hex",
        }

        url = f"{self.base_url}/t2a_v2"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=120.0) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        base_resp = data.get("base_resp", {})
        if base_resp.get("status_code") != 0:
            raise RuntimeError(f"TTS API error: {base_resp.get('status_msg', 'unknown error')}")

        audio_hex = data.get("data", {}).get("audio")
        if not audio_hex:
            raise RuntimeError("TTS API returned no audio data")

        return bytes.fromhex(audio_hex)

    def _split_text(self, text: str, max_chars: int = 3000) -> list[str]:
        if len(text) <= max_chars:
            return [text]

        chunks = []
        remaining = text
        while remaining:
            if len(remaining) <= max_chars:
                chunks.append(remaining)
                break

            split_pos = remaining.rfind("\n", 0, max_chars)
            if split_pos == -1:
                split_pos = remaining.rfind("。", 0, max_chars)
            if split_pos == -1:
                split_pos = remaining.rfind("，", 0, max_chars)
            if split_pos == -1:
                split_pos = max_chars

            chunks.append(remaining[: split_pos + 1])
            remaining = remaining[split_pos + 1 :]

        return chunks
