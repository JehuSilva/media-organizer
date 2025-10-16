from pathlib import Path

from media_organizer.config import OrganizerConfig, load_template_profiles
from media_organizer.templates import DEFAULT_TEMPLATES


def test_load_template_profiles():
    path = Path(__file__).parent / "data" / "profiles.yaml"
    profiles = load_template_profiles(path)
    assert "eventos" in profiles
    assert profiles["eventos"].template == "{year}/{month:02d}/{evento}"


def test_resolve_template_uses_defaults(tmp_path):
    config = OrganizerConfig(
        source=tmp_path,
        destination=tmp_path / "dest",
        template="default",
    )
    template_value = config.resolve_template({})
    assert template_value == DEFAULT_TEMPLATES["default"]


def test_default_templates_include_month_name():
    assert DEFAULT_TEMPLATES["year_month_name"] == "{year}/{month_name}"
