"""Configuration models and helpers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Literal, Optional

import yaml
from pydantic import BaseModel, Field, validator

from .templates import DEFAULT_TEMPLATES

logger = logging.getLogger(__name__)


class TemplateProfile(BaseModel):
    name: str
    template: str
    description: Optional[str] = None


class OrganizerConfig(BaseModel):
    source: Path
    destination: Path
    action: Literal["move", "copy", "link"] = "move"
    template: str = DEFAULT_TEMPLATES["default"]
    dry_run: bool = False
    recursive: bool = True
    follow_symlinks: bool = False
    include_extensions: list[str] = Field(default_factory=list)
    exclude_extensions: list[str] = Field(default_factory=list)
    extra: dict[str, str] = Field(default_factory=dict)

    @validator("source", "destination", pre=True)
    def _expand_path(cls, value: object) -> Path:
        if isinstance(value, Path):
            return value.expanduser()
        if isinstance(value, str):
            return Path(value).expanduser()
        raise TypeError("Las rutas deben ser cadenas o instancias de Path.")

    @validator("template")
    def _validate_template(cls, value: str) -> str:
        if not value:
            raise ValueError("El template no puede estar vacío.")
        return value

    def resolve_template(self, profiles: Dict[str, TemplateProfile]) -> str:
        if self.template in DEFAULT_TEMPLATES:
            return DEFAULT_TEMPLATES[self.template]
        if self.template in profiles:
            return profiles[self.template].template
        return self.template

    def normalized_include_extensions(self) -> set[str]:
        return {ext.lower() if ext.startswith(".") else f".{ext.lower()}" for ext in self.include_extensions}

    def normalized_exclude_extensions(self) -> set[str]:
        return {ext.lower() if ext.startswith(".") else f".{ext.lower()}" for ext in self.exclude_extensions}


def load_template_profiles(path: Path) -> Dict[str, TemplateProfile]:
    if not path.exists():
        logger.debug("El archivo de perfiles %s no existe; se utilizarán los templates por defecto.", path)
        return {}

    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    profiles: Dict[str, TemplateProfile] = {}
    for item in raw.get("profiles", []):
        profile = TemplateProfile(**item)
        profiles[profile.name] = profile
    return profiles
