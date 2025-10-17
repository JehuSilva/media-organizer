"""Command line interface for the media organizer."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

import typer
from rich.console import Console
from rich.table import Table

from .config import OrganizerConfig, load_template_profiles
from .media_scanner import ScanOptions, iter_media_files
from .organizer import MediaOrganizer, OrganizeSummary
from .templates import DEFAULT_TEMPLATES

console = Console()
app = typer.Typer(add_completion=False, help="Organiza fotos y videos en carpetas.")


def _parse_extra(extra: Optional[List[str]]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    if not extra:
        return result
    for item in extra:
        if "=" not in item:
            raise typer.BadParameter(f"El argumento extra '{item}' debe tener el formato clave=valor")
        key, value = item.split("=", 1)
        result[key] = value
    return result


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )


@app.command()
def run(
    source: Path = typer.Option(..., "--source", "-s", help="Directorio de origen a analizar."),
    destination: Path = typer.Option(..., "--destination", "-d", help="Directorio de destino."),
    profile: str = typer.Option("default", "--profile", "-p", help="Nombre del perfil de template a usar."),
    template: Optional[str] = typer.Option(None, "--template", help="Template personalizado (ignora --profile)."),
    profiles_path: Optional[Path] = typer.Option(
        None,
        "--profiles-path",
        help="Archivo YAML con perfiles adicionales.",
    ),
    action: str = typer.Option("move", "--action", "-a", help="Acción a aplicar sobre los archivos (move|copy|link)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Muestra los cambios sin mover archivos."),
    recursive: bool = typer.Option(True, "--recursive/--no-recursive", help="Buscar archivos de forma recursiva."),
    follow_symlinks: bool = typer.Option(False, "--follow-symlinks", help="Seguir enlaces simbólicos."),
    include_ext: Optional[List[str]] = typer.Option(
        None,
        "--include-ext",
        help="Extensiones permitidas (puede repetirse).",
    ),
    exclude_ext: Optional[List[str]] = typer.Option(
        None,
        "--exclude-ext",
        help="Extensiones a excluir (puede repetirse).",
    ),
    extra: Optional[List[str]] = typer.Option(
        None,
        "--extra",
        help="Pares clave=valor para usar en el template.",
    ),
    log_level: str = typer.Option("INFO", "--log-level", help="Nivel de logging (DEBUG, INFO, WARNING, ERROR)."),
) -> None:
    """Organiza archivos multimedia según el template configurado."""
    _setup_logging(log_level)

    profiles = load_template_profiles(profiles_path) if profiles_path else {}

    if profile not in DEFAULT_TEMPLATES and profile not in profiles:
        raise typer.BadParameter(f"El perfil '{profile}' no está definido.")

    template_value = template or profile
    action = action.lower()
    if action not in {"move", "copy", "link"}:
        raise typer.BadParameter("La acción debe ser move, copy o link.", param_name="action")
    extra_values = _parse_extra(extra)

    config = OrganizerConfig(
        source=source,
        destination=destination,
        action=action,
        template=template_value,
        dry_run=dry_run,
        recursive=recursive,
        follow_symlinks=follow_symlinks,
        include_extensions=include_ext or [],
        exclude_extensions=exclude_ext or [],
        extra=extra_values,
    )

    scan_options = ScanOptions(
        recursive=config.recursive,
        follow_symlinks=config.follow_symlinks,
        include_extensions=config.normalized_include_extensions(),
        exclude_extensions=config.normalized_exclude_extensions(),
    )

    organizer = MediaOrganizer(config=config, profiles=profiles)
    files = list(iter_media_files(config.source, scan_options))

    if not files:
        console.print("[yellow]No se encontraron archivos para procesar.[/yellow]")
        raise typer.Exit(code=0)

    console.print(f"Procesando {len(files)} archivos desde {config.source} hacia {config.destination}...")
    summary = organizer.organize(files)
    _render_summary(summary)


def _render_summary(summary: OrganizeSummary) -> None:
    table = Table(title="Resumen de organización")
    table.add_column("Archivo origen", style="cyan", no_wrap=True)
    table.add_column("Destino", style="green")
    table.add_column("Estado", style="magenta")
    table.add_column("Categoría", style="yellow")
    table.add_column("Mensaje", style="white")

    for result in summary.results:
        category_label = "-"
        if result.category is not None:
            try:
                category_label = result.category.label()
            except AttributeError:
                category_label = str(result.category)
        table.add_row(
            str(result.source),
            str(result.destination),
            result.status,
            category_label,
            result.message or "",
        )

    console.print(table)
    summary_table = Table(title="Resumen por estado")
    summary_table.add_column("Estado", style="magenta")
    summary_table.add_column("Cantidad", style="cyan", justify="right")
    summary_table.add_column("Porcentaje", style="white", justify="right")

    counts = summary.status_counts()
    ordered_statuses = ["moved", "copied", "linked", "dry-run", "skipped", "failed"]
    total = summary.total

    for status in ordered_statuses:
        value = counts.get(status, 0)
        percentage = f"{(value / total * 100):.1f}%" if total else "0.0%"
        summary_table.add_row(status, str(value), percentage)

    remaining_statuses = sorted(set(counts.keys()) - set(ordered_statuses))
    for status in remaining_statuses:
        value = counts[status]
        percentage = f"{(value / total * 100):.1f}%" if total else "0.0%"
        summary_table.add_row(status, str(value), percentage)

    summary_table.add_row("total", str(total), "100.0%" if total else "0.0%")
    console.print(summary_table)

    category_counts = summary.category_counts()
    if category_counts:
        category_table = Table(title="Resumen por categoría")
        category_table.add_column("Categoría", style="yellow")
        category_table.add_column("Cantidad", style="cyan", justify="right")
        category_table.add_column("Porcentaje", style="white", justify="right")

        for label, value in category_counts.items():
            percentage = f"{(value / total * 100):.1f}%" if total else "0.0%"
            category_table.add_row(label, str(value), percentage)
        category_table.add_row("total", str(total), "100.0%" if total else "0.0%")
        console.print(category_table)
