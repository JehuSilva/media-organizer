import os
from datetime import datetime, timezone
from pathlib import Path

from media_organizer.config import OrganizerConfig
from media_organizer.media_scanner import ScanOptions, iter_media_files
from media_organizer.organizer import MediaOrganizer
from media_organizer.metadata import MediaMetadata, MediaType, TimestampSource


def _set_file_timestamp(path: Path, dt: datetime) -> None:
    timestamp = dt.replace(tzinfo=timezone.utc).timestamp()
    os.utime(path, (timestamp, timestamp))


def test_media_organizer_resolves_collisions(tmp_path, monkeypatch):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()

    file_path = source / "photo.jpg"
    file_path.write_bytes(b"test")
    _set_file_timestamp(file_path, datetime(2023, 1, 2, 12, 0))

    preexisting_dir = destination / "2023/01"
    preexisting_dir.mkdir(parents=True)
    (preexisting_dir / "photo.jpg").write_bytes(b"existing")

    def fake_extract(path: Path) -> MediaMetadata:
        return MediaMetadata(
            source_path=path,
            media_type=MediaType.IMAGE,
            captured_at=datetime(2023, 1, 2, 12, 0, tzinfo=timezone.utc),
            original_name=path.name,
            timestamp_source=TimestampSource.METADATA,
        )

    monkeypatch.setattr("media_organizer.organizer.extract_metadata", fake_extract)

    config = OrganizerConfig(
        source=source,
        destination=destination,
        action="copy",
        template="default",
        dry_run=False,
    )

    organizer = MediaOrganizer(config=config)
    files = list(iter_media_files(source, ScanOptions(recursive=True)))
    summary = organizer.organize(files)

    assert summary.copied == 1
    new_file = destination / "2023/01" / "photo_1.jpg"
    assert new_file.exists()
    assert summary.failed == 0
    assert summary.status_counts()["copied"] == 1


def test_media_organizer_sends_unreliable_files_to_unknown(tmp_path, monkeypatch):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()

    file_path = source / "photo.jpg"
    file_path.write_bytes(b"test")

    def fake_extract(path: Path) -> MediaMetadata:
        return MediaMetadata(
            source_path=path,
            media_type=MediaType.IMAGE,
            captured_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
            original_name=path.name,
            timestamp_source=TimestampSource.FILE_MODIFICATION,
        )

    monkeypatch.setattr("media_organizer.organizer.extract_metadata", fake_extract)

    config = OrganizerConfig(
        source=source,
        destination=destination,
        action="copy",
        template="default",
        dry_run=True,
    )

    organizer = MediaOrganizer(config=config)
    files = list(iter_media_files(source, ScanOptions(recursive=True)))
    summary = organizer.organize(files)

    assert summary.dry_run == 1
    expected = destination / "unknown_date" / "photo.jpg"
    assert summary.results[0].destination == expected
    assert summary.status_counts()["dry-run"] == 1
