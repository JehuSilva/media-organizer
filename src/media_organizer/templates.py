"""Template helpers for organizing media into directories."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Optional

from .metadata import MediaMetadata

MONTH_NAMES_ES = [
    "",
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]

MONTH_NAMES_ES_SHORT = [
    "",
    "ene",
    "feb",
    "mar",
    "abr",
    "may",
    "jun",
    "jul",
    "ago",
    "sep",
    "oct",
    "nov",
    "dic",
]

DEFAULT_TEMPLATES: Dict[str, str] = {
    "default": "{year}/{month:02d}",
    "year_month_day": "{year}/{month:02d}/{day:02d}",
    "camera": "{camera_make}/{camera_model}/{year}/{month:02d}",
    "year_month_name": "{year}/{month_name}",
    "year_month_name_short": "{year}/{month_name_short}",
}

VALID_PLACEHOLDER_RE = re.compile(r"{([a-zA-Z_][a-zA-Z0-9_]*)(:[^}]*)?}")


def available_placeholders() -> set[str]:
    return {
        "year",
        "month",
        "day",
        "hour",
        "minute",
        "second",
        "stem",
        "ext",
        "camera_make",
        "camera_model",
        "month_name",
        "month_name_short",
    }


def build_context(metadata: MediaMetadata, extra: Optional[dict[str, str]] = None) -> dict[str, object]:
    dt = metadata.captured_at
    context: dict[str, object] = {
        "year": dt.year,
        "month": dt.month,
        "day": dt.day,
        "hour": dt.hour,
        "minute": dt.minute,
        "second": dt.second,
        "stem": metadata.stem,
        "ext": metadata.suffix.lstrip("."),
        "camera_make": _slug(metadata.camera_make) if metadata.camera_make else "unknown",
        "camera_model": _slug(metadata.camera_model) if metadata.camera_model else "unknown",
        "month_name": MONTH_NAMES_ES[dt.month],
        "month_name_short": MONTH_NAMES_ES_SHORT[dt.month],
    }
    if extra:
        context.update(extra)
    return context


def render_template(
    metadata: MediaMetadata,
    template: str,
    extra: Optional[dict[str, str]] = None,
) -> Path:
    _validate_template(template, extra or {})
    context = build_context(metadata, extra)
    relative = template.format(**context)
    return Path(relative)


def _validate_template(template: str, extra: dict[str, str]) -> None:
    allowed = available_placeholders() | set(extra.keys())
    unmatched = [
        match.group(1)
        for match in VALID_PLACEHOLDER_RE.finditer(template)
        if match.group(1) not in allowed
    ]
    if unmatched:
        raise ValueError(
            f"El template contiene placeholders desconocidos: {', '.join(sorted(set(unmatched)))}"
        )


def _slug(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-{2,}", "-", value)
    return value.strip("-") or "unknown"
