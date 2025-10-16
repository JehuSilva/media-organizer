"""Utilities for extracting media metadata."""

from __future__ import annotations

import enum
import json
import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dateutil import parser as date_parser
from PIL import ExifTags, Image

logger = logging.getLogger(__name__)

try:  # pragma: no cover - se usa únicamente en producción con soporte HEIC
    from pillow_heif import register_heif_opener  # type: ignore[import]

    register_heif_opener()
except ImportError:  # pragma: no cover
    logger.debug(
        "pillow-heif no está instalado; los archivos HEIC se procesarán sin soporte nativo"
    )


class MediaType(enum.Enum):
    IMAGE = "image"
    VIDEO = "video"
    OTHER = "other"


class TimestampSource(enum.Enum):
    METADATA = "metadata"
    FILE_CREATION = "file_creation"
    FILE_MODIFICATION = "file_modification"
    UNKNOWN = "unknown"


@dataclass
class MediaMetadata:
    """Metadata relevante para organizar archivos multimedia."""

    source_path: Path
    media_type: MediaType
    captured_at: datetime
    camera_make: Optional[str] = None
    camera_model: Optional[str] = None
    original_name: Optional[str] = None
    timestamp_source: TimestampSource = TimestampSource.METADATA

    @property
    def stem(self) -> str:
        return self.source_path.stem

    @property
    def suffix(self) -> str:
        return self.source_path.suffix.lower()

    @property
    def has_reliable_timestamp(self) -> bool:
        return self.timestamp_source in {TimestampSource.METADATA, TimestampSource.FILE_CREATION}


IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".tiff",
    ".tif",
    ".heic",
    ".heif",
    ".raw",
    ".cr2",
    ".nef",
    ".arw",
}

VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".m4v",
    ".mkv",
    ".avi",
    ".wmv",
    ".mpg",
    ".mpeg",
}


def detect_media_type(path: Path) -> MediaType:
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return MediaType.IMAGE
    if suffix in VIDEO_EXTENSIONS:
        return MediaType.VIDEO
    return MediaType.OTHER


def extract_metadata(path: Path) -> MediaMetadata:
    media_type = detect_media_type(path)
    captured_at: Optional[datetime] = None
    camera_make: Optional[str] = None
    camera_model: Optional[str] = None
    timestamp_source = TimestampSource.UNKNOWN

    if media_type == MediaType.IMAGE:
        captured_at, camera_make, camera_model, timestamp_source = _extract_image_metadata(path)
    elif media_type == MediaType.VIDEO:
        captured_at, timestamp_source = _extract_video_metadata(path)

    if captured_at is None:
        captured_at, timestamp_source = _filesystem_timestamp(path)

    return MediaMetadata(
        source_path=path,
        media_type=media_type,
        captured_at=captured_at,
        camera_make=camera_make,
        camera_model=camera_model,
        original_name=path.name,
        timestamp_source=timestamp_source,
    )


def _extract_image_metadata(
    path: Path,
) -> tuple[Optional[datetime], Optional[str], Optional[str], TimestampSource]:
    try:
        with Image.open(path) as img:
            exif = _read_exif_dict(img)
            if not exif:
                return None, None, None, TimestampSource.UNKNOWN
    except Exception as exc:  # pragma: no cover - PIL lanza errores variados por archivos corruptos
        logger.debug("No fue posible leer EXIF de %s: %s", path, exc)
        return None, None, None, TimestampSource.UNKNOWN

    date_value = exif.get("DateTimeOriginal") or exif.get("DateTimeDigitized") or exif.get(
        "DateTime"
    )
    captured_at = _parse_exif_datetime(str(date_value)) if date_value else None
    timestamp_source = TimestampSource.METADATA if captured_at else TimestampSource.UNKNOWN

    make = exif.get("Make")
    model = exif.get("Model")
    return captured_at, _clean_string(make), _clean_string(model), timestamp_source


def _extract_video_metadata(path: Path) -> tuple[Optional[datetime], TimestampSource]:
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_entries",
        "format_tags=creation_time",
        str(path),
    ]
    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        logger.debug("ffprobe no está instalado; usando marca de tiempo del sistema.")
        return None, TimestampSource.UNKNOWN
    except subprocess.CalledProcessError as exc:
        logger.debug("ffprobe falló en %s: %s", path, exc)
        return None, TimestampSource.UNKNOWN

    try:
        payload = json.loads(result.stdout)
        creation_time = payload.get("format", {}).get("tags", {}).get("creation_time")
    except json.JSONDecodeError:
        logger.debug("ffprobe devolvió una salida no válida para %s", path)
        return None, TimestampSource.UNKNOWN

    if not creation_time:
        return None, TimestampSource.UNKNOWN

    try:
        parsed = date_parser.isoparse(creation_time)
    except (ValueError, TypeError):
        logger.debug("No se pudo convertir creation_time %s en %s", creation_time, path)
        return None, TimestampSource.UNKNOWN

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(), TimestampSource.METADATA


def _filesystem_timestamp(path: Path) -> tuple[datetime, TimestampSource]:
    stat = path.stat()
    timestamp_source = TimestampSource.UNKNOWN

    # Prefer birth/creation time when the platform exposes it.
    birthtime = getattr(stat, "st_birthtime", None)
    if birthtime:
        timestamp = birthtime
        timestamp_source = TimestampSource.FILE_CREATION
    else:
        timestamp = stat.st_mtime or stat.st_ctime
        timestamp_source = TimestampSource.FILE_MODIFICATION

    dt = datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone()
    return dt, timestamp_source


def _parse_exif_datetime(value: str) -> Optional[datetime]:
    try:
        dt = datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
    except (ValueError, TypeError):
        logger.debug("Formato EXIF inesperado: %s", value)
        return None
    return dt.replace(tzinfo=timezone.utc).astimezone()


def _read_exif_dict(image: Image.Image) -> dict[str, object]:
    """Devuelve un diccionario legible de etiquetas EXIF."""
    exif_data: dict[str, object] = {}
    raw_exif = None
    try:
        raw_exif = image.getexif()  # type: ignore[attr-defined]
    except AttributeError:
        raw_exif = None

    if raw_exif:
        for tag_id, value in raw_exif.items():
            tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
            exif_data[tag_name] = value

    if not exif_data:
        exif_bytes = getattr(image, "info", {}).get("exif")
        if exif_bytes and hasattr(Image, "Exif"):
            try:
                exif = Image.Exif()
                exif.load(exif_bytes)
                for tag_id, value in exif.items():
                    tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
                    exif_data[tag_name] = value
            except Exception as exc:  # pragma: no cover - Pillow puede no soportar ciertos EXIF
                logger.debug(
                    "No se pudo decodificar EXIF bytes para %s: %s",
                    getattr(image, "filename", "desconocido"),
                    exc,
                )

    return exif_data


def _clean_string(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return str(value).strip() or None
