"""Ferramentas de mídia: ffprobe, FFmpeg e renderização de página de PDF.

Tudo aqui é operação local, sem custo e sem enviar nada para fora.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from app.config import ffmpeg_disponivel, settings

logger = logging.getLogger(__name__)


def disponivel() -> bool:
    """Existe FFmpeg nesta instalação? Na Vercel, não."""
    return ffmpeg_disponivel()


# Estimativa grosseira de duração quando não há ffprobe: os áudios do WhatsApp
# são Opus de baixa taxa, algo perto de 2,5 KB por segundo de fala.
BYTES_POR_SEGUNDO_OPUS = 2_500


def estimar_duracao(tamanho_bytes: int, mime: str | None = None) -> float:
    """Duração aproximada pelo tamanho do arquivo, para estimar custo sem ffprobe."""
    if tamanho_bytes <= 0:
        return 0.0
    taxa = BYTES_POR_SEGUNDO_OPUS
    if mime and ("mpeg" in mime or "mp3" in mime):
        taxa = 16_000  # MP3 costuma vir bem mais gordo
    elif mime and "wav" in mime:
        taxa = 32_000
    return round(tamanho_bytes / taxa, 1)


# Um vídeo do WhatsApp gira em torno de 150 KB por segundo (imagem + som). Serve
# só para estimar custo quando não há ffprobe para perguntar a duração real.
BYTES_POR_SEGUNDO_VIDEO = 150_000


def estimar_duracao_do_video(tamanho_bytes: int) -> float:
    """Duração aproximada de um vídeo pelo tamanho, sem ffprobe."""
    if tamanho_bytes <= 0:
        return 0.0
    return round(tamanho_bytes / BYTES_POR_SEGUNDO_VIDEO, 1)


class MediaToolError(RuntimeError):
    pass


@dataclass
class MediaInfo:
    duration_seconds: float | None = None
    has_audio: bool = False
    has_video: bool = False
    audio_codec: str | None = None
    video_codec: str | None = None
    width: int | None = None
    height: int | None = None


async def _run(command: list[str], timeout: int = 900) -> tuple[int, bytes, bytes]:
    if not disponivel():
        raise MediaToolError("FFmpeg não está instalado nesta instalação")
    process = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        raise MediaToolError(f"{command[0]} excedeu o tempo limite") from None
    return process.returncode or 0, stdout, stderr


async def probe(path: Path) -> MediaInfo:
    """Duração e codecs do arquivo. Devolve MediaInfo vazio se o ffprobe falhar."""
    if not disponivel():
        return MediaInfo()
    code, stdout, stderr = await _run(
        [
            settings.ffprobe_bin, "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ],
        timeout=120,
    )
    if code != 0:
        logger.debug("ffprobe falhou em %s: %s", path.name, stderr[:200])
        return MediaInfo()

    try:
        data = json.loads(stdout or b"{}")
    except json.JSONDecodeError:
        return MediaInfo()

    info = MediaInfo()
    duration = data.get("format", {}).get("duration")
    if duration:
        try:
            info.duration_seconds = float(duration)
        except ValueError:
            pass
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "audio":
            info.has_audio = True
            info.audio_codec = stream.get("codec_name")
        elif stream.get("codec_type") == "video":
            info.has_video = True
            info.video_codec = stream.get("codec_name")
            info.width = stream.get("width")
            info.height = stream.get("height")
            if info.duration_seconds is None and stream.get("duration"):
                try:
                    info.duration_seconds = float(stream["duration"])
                except ValueError:
                    pass
    return info


async def convert_audio(source: Path, target: Path, bitrate: str = "64k") -> Path:
    """Converte para MP3 mono 16 kHz — formato aceito por qualquer provedor de STT."""
    target.parent.mkdir(parents=True, exist_ok=True)
    code, _stdout, stderr = await _run(
        [
            settings.ffmpeg_bin, "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000",
            "-b:a", bitrate, str(target),
        ]
    )
    if code != 0 or not target.exists():
        raise MediaToolError(f"não foi possível converter o áudio: {stderr[-300:].decode(errors='replace')}")
    return target


async def split_audio(source: Path, out_dir: Path, seconds: int) -> list[Path]:
    """Divide o áudio em pedaços de duração fixa, mantendo a ordem no nome do arquivo."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / "chunk-%03d.mp3")
    code, _stdout, stderr = await _run(
        [
            settings.ffmpeg_bin, "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000",
            "-b:a", "64k", "-f", "segment", "-segment_time", str(seconds), pattern,
        ]
    )
    chunks = sorted(out_dir.glob("chunk-*.mp3"))
    if code != 0 and not chunks:
        raise MediaToolError(f"não foi possível dividir o áudio: {stderr[-300:].decode(errors='replace')}")
    return chunks


async def extract_audio_track(source: Path, target: Path) -> Path | None:
    """Extrai a trilha de áudio de um vídeo. None quando o vídeo não tem áudio."""
    info = await probe(source)
    if not info.has_audio:
        return None
    return await convert_audio(source, target)


async def extract_frames(source: Path, out_dir: Path, max_frames: int) -> list[Path]:
    """Seleciona frames representativos: mudanças de cena e, se faltar, pontos fixos.

    Sempre inclui começo, meio e fim, e nunca passa do teto configurado.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    info = await probe(source)
    duration = info.duration_seconds or 0

    scene_dir = out_dir / "cenas"
    scene_dir.mkdir(exist_ok=True)
    await _run(
        [
            settings.ffmpeg_bin, "-y", "-i", str(source),
            "-vf", "select='gt(scene,0.35)',scale=768:-2",
            "-vsync", "vfr", "-frames:v", str(max_frames), str(scene_dir / "cena-%03d.jpg"),
        ],
        timeout=600,
    )
    frames = sorted(scene_dir.glob("cena-*.jpg"))

    anchors: list[float] = []
    if duration > 0:
        anchors = [duration * ratio for ratio in (0.02, 0.5, 0.98)]
    remaining = max_frames - len(frames)
    if remaining > 0 and duration > 0:
        extra = max(0, remaining - len(anchors))
        step = duration / (extra + 1) if extra else 0
        anchors += [step * (i + 1) for i in range(extra)]

    fixed_dir = out_dir / "fixos"
    fixed_dir.mkdir(exist_ok=True)
    for position, moment in enumerate(sorted(anchors)[: max(0, max_frames - len(frames))]):
        target = fixed_dir / f"t-{position:03d}.jpg"
        await _run(
            [
                settings.ffmpeg_bin, "-y", "-ss", f"{moment:.2f}", "-i", str(source),
                "-frames:v", "1", "-vf", "scale=768:-2", str(target),
            ],
            timeout=180,
        )
        if target.exists():
            frames.append(target)

    return frames[:max_frames]
