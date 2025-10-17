"""Utilities for extracting media metadata."""

from __future__ import annotations

import enum
import json
import logging
import subprocess
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Sequence
from xml.etree import ElementTree as ET

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

try:  # pragma: no cover - dependencias opcionales
    import mutagen  # type: ignore
except ImportError:  # pragma: no cover
    mutagen = None

try:  # pragma: no cover
    from pypdf import PdfReader  # type: ignore
except ImportError:  # pragma: no cover
    PdfReader = None  # type: ignore


class MediaType(enum.Enum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    OTHER = "other"


class MediaCategory(enum.Enum):
    PHOTOS_VIDEOS = ("Fotos y Videos", "Fotos_y_Videos")
    MUSIC = ("Musica", "Musica")
    DOCUMENTS = ("Documentos", "Documentos")
    OTHER = ("Otros", "Otros")

    def label(self) -> str:
        return self.value[0]

    def folder_name(self) -> str:
        return self.value[1]


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
    category: MediaCategory
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
    ".3gp",
    ".webm",
    ".mts",
    ".m2ts",
}

AUDIO_EXTENSIONS = {
    ".mp3",
    ".aac",
    ".flac",
    ".wav",
    ".ogg",
    ".oga",
    ".m4a",
    ".wma",
    ".aiff",
    ".aif",
}

DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".txt",
    ".rtf",
    ".odt",
    ".ods",
    ".odp",
}


def detect_media_type(path: Path) -> MediaType:
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return MediaType.IMAGE
    if suffix in VIDEO_EXTENSIONS:
        return MediaType.VIDEO
    if suffix in AUDIO_EXTENSIONS:
        return MediaType.AUDIO
    if suffix in DOCUMENT_EXTENSIONS:
        return MediaType.DOCUMENT
    return MediaType.OTHER


def resolve_category(media_type: MediaType) -> MediaCategory:
    if media_type in {MediaType.IMAGE, MediaType.VIDEO}:
        return MediaCategory.PHOTOS_VIDEOS
    if media_type == MediaType.AUDIO:
        return MediaCategory.MUSIC
    if media_type == MediaType.DOCUMENT:
        return MediaCategory.DOCUMENTS
    return MediaCategory.OTHER


def extract_metadata(path: Path) -> MediaMetadata:
    media_type = detect_media_type(path)
    category = resolve_category(media_type)
    captured_at: Optional[datetime] = None
    camera_make: Optional[str] = None
    camera_model: Optional[str] = None
    timestamp_source = TimestampSource.UNKNOWN

    if media_type == MediaType.IMAGE:
        captured_at, camera_make, camera_model, timestamp_source = _extract_image_metadata(path)
    elif media_type == MediaType.VIDEO:
        captured_at, timestamp_source = _extract_video_metadata(path)
    elif media_type == MediaType.AUDIO:
        captured_at, timestamp_source = _extract_audio_metadata(path)
    elif media_type == MediaType.DOCUMENT:
        captured_at, timestamp_source = _extract_document_metadata(path)

    if captured_at is None:
        captured_at, timestamp_source = _filesystem_timestamp(path)

    return MediaMetadata(
        source_path=path,
        media_type=media_type,
        category=category,
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
        (
            "format_tags=creation_time,"
            "com.apple.quicktime.creationdate,"
            "create_date,"
            "creation_date,"
            "date"
        ),
        "-show_entries",
        (
            "stream_tags=creation_time,"
            "com.apple.quicktime.creationdate,"
            "create_date,"
            "creation_date,"
            "date"
        ),
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
    except json.JSONDecodeError:
        logger.debug("ffprobe devolvió una salida no válida para %s", path)
        return None, TimestampSource.UNKNOWN

    tags_sources: list[dict[str, str]] = []
    format_tags = payload.get("format", {}).get("tags")
    if isinstance(format_tags, dict):
        tags_sources.append(format_tags)

    for stream in payload.get("streams", []) or []:
        stream_tags = stream.get("tags")
        if isinstance(stream_tags, dict):
            tags_sources.append(stream_tags)

    tag_keys = [
        "com.apple.quicktime.creationdate",
        "creation_time",
        "create_date",
        "creation_date",
        "date",
        "CreationDate",
    ]

    for tags in tags_sources:
        for key in tag_keys:
            value = tags.get(key)
            if value:
                parsed = _parse_flexible_datetime(value)
                if parsed:
                    return parsed, TimestampSource.METADATA

    return None, TimestampSource.UNKNOWN


def _extract_audio_metadata(path: Path) -> tuple[Optional[datetime], TimestampSource]:
    if mutagen is None:
        logger.debug("mutagen no está instalado; usando timestamp del sistema para %s", path)
        return None, TimestampSource.UNKNOWN

    try:
        audio = mutagen.File(path)  # type: ignore[attr-defined]
    except Exception as exc:  # pragma: no cover - mutagen lanza distintos errores según formato
        logger.debug("No fue posible leer metadatos de audio en %s: %s", path, exc)
        return None, TimestampSource.UNKNOWN

    if audio is None:
        return None, TimestampSource.UNKNOWN

    tags = getattr(audio, "tags", None)
    if not tags:
        return None, TimestampSource.UNKNOWN

    tag_candidates = [
        "TDRC",
        "TDOR",
        "TORY",
        "TDRL",
        "DATE",
        "Year",
        "YEAR",
        "year",
        "TYER",
        "©day",
    ]

    for key in tag_candidates:
        value = tags.get(key)
        if value is None:
            continue
        normalized = _normalize_tag_value(value)
        if not normalized:
            continue
        parsed = _parse_flexible_datetime(normalized)
        if parsed:
            return parsed, TimestampSource.METADATA

    return None, TimestampSource.UNKNOWN


def _extract_document_metadata(path: Path) -> tuple[Optional[datetime], TimestampSource]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf_metadata(path)
    if suffix in {".docx", ".pptx", ".xlsx"}:
        return _extract_office_metadata(path, "docProps/core.xml", _parse_flexible_datetime)
    if suffix in {".odt", ".ods", ".odp"}:
        return _extract_office_metadata(path, "meta.xml", _parse_odf_datetime)
    return None, TimestampSource.UNKNOWN


def _extract_pdf_metadata(path: Path) -> tuple[Optional[datetime], TimestampSource]:
    if PdfReader is None:
        logger.debug("pypdf no está instalado; usando timestamp del sistema para %s", path)
        return None, TimestampSource.UNKNOWN

    try:
        reader = PdfReader(str(path))
    except Exception as exc:  # pragma: no cover - pypdf puede lanzar diversas excepciones
        logger.debug("No fue posible leer metadatos de PDF en %s: %s", path, exc)
        return None, TimestampSource.UNKNOWN

    metadata = getattr(reader, "metadata", None) or getattr(reader, "documentInfo", None)
    if not metadata:
        return None, TimestampSource.UNKNOWN

    candidates = [
        getattr(metadata, "creation_date", None),
        getattr(metadata, "modification_date", None),
        metadata.get("/CreationDate") if hasattr(metadata, "get") else None,
        metadata.get("/ModDate") if hasattr(metadata, "get") else None,
    ]

    for value in candidates:
        if not value:
            continue
        parsed = _parse_pdf_date(str(value))
        if parsed:
            return parsed, TimestampSource.METADATA

    return None, TimestampSource.UNKNOWN


def _extract_office_metadata(
    path: Path,
    core_path: str,
    parser: Callable[[str], Optional[datetime]],
) -> tuple[Optional[datetime], TimestampSource]:
    try:
        with zipfile.ZipFile(path) as archive:
            with archive.open(core_path) as handle:
                data = handle.read()
    except (FileNotFoundError, KeyError, zipfile.BadZipFile) as exc:
        logger.debug("No se encontró metadata %s en %s: %s", core_path, path, exc)
        return None, TimestampSource.UNKNOWN

    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        logger.debug("No se pudo parsear metadata XML en %s: %s", path, exc)
        return None, TimestampSource.UNKNOWN

    if core_path == "docProps/core.xml":
        namespaces = {
            "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
            "dc": "http://purl.org/dc/elements/1.1/",
            "dcterms": "http://purl.org/dc/terms/",
        }
        candidates = [
            root.find("dcterms:created", namespaces),
            root.find("dcterms:modified", namespaces),
        ]
    else:
        namespaces = {
            "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
            "meta": "urn:oasis:names:tc:opendocument:xmlns:meta:1.0",
        }
        candidates = [
            root.find(".//meta:creation-date", namespaces),
            root.find(".//dc:date", {"dc": "http://purl.org/dc/elements/1.1/"}),
        ]

    for node in candidates:
        if node is None or not node.text:
            continue
        parsed = parser(node.text.strip())
        if parsed:
            return parsed, TimestampSource.METADATA

    return None, TimestampSource.UNKNOWN


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


def _normalize_tag_value(value: object) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8", errors="ignore")
        except Exception:  # pragma: no cover - decodificaciones variadas
            value = value.decode("latin-1", errors="ignore")
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            normalized = _normalize_tag_value(item)
            if normalized:
                return normalized
        return None
    text = getattr(value, "text", None)
    if text is not None:
        return _normalize_tag_value(text)
    try:
        string_value = str(value)
    except Exception:
        return None
    return string_value.strip() or None


def _parse_flexible_datetime(value: str) -> Optional[datetime]:
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    cleaned = cleaned.replace("\\", " ")
    try:
        parsed = date_parser.parse(cleaned)
    except (ValueError, TypeError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone()


def _parse_pdf_date(value: str) -> Optional[datetime]:
    if not value:
        return None
    cleaned = value.strip()
    if cleaned.startswith("D:"):
        cleaned = cleaned[2:]
    cleaned = cleaned.replace("'", "")
    cleaned = cleaned.replace(" ", "")

    if len(cleaned) >= 14 and cleaned[:14].isdigit():
        main = cleaned[:14]
        remainder = cleaned[14:]
        formatted = (
            f"{main[0:4]}-{main[4:6]}-{main[6:8]}T"
            f"{main[8:10]}:{main[10:12]}:{main[12:14]}"
        )
        if remainder:
            formatted += remainder
    else:
        formatted = cleaned

    return _parse_flexible_datetime(formatted)


def _parse_odf_datetime(value: str) -> Optional[datetime]:
    return _parse_flexible_datetime(value)


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
