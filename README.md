# Media Organizer

Automatic organizer for photos, videos, audio and documents with configurable destination templates.

## Características

- Extrae metadatos (EXIF, ID3, PDF, Office) para ordenar archivos multimedia y documentos.
- Clasifica automáticamente en categorías (`Fotos y Videos`, `Musica`, `Documentos`, `Otros`).
- Dentro de cada categoría organiza por año/mes (personalizable mediante plantillas).
- Modo `dry-run` para validar resultados sin mover archivos.
- Soporte para HEIC mediante `pillow-heif` y compatibilidad ampliada con videos (ffprobe y tags DJI).
- Archivos sin fecha confiable se ubican automáticamente en `unknown_date/` dentro de su categoría.
- Empaquetado multiplataforma mediante PyInstaller (scripts incluidos posteriormente).

## Requisitos

- Python 3.10 o superior.
- [FFmpeg](https://ffmpeg.org/) instalado y disponible en el `PATH` para extraer metadatos de video/audio.
- Las dependencias se instalan con `pip install -e .` e incluyen `mutagen` (audio) y `pypdf` (PDF).

## Uso rápido

```bash
python -m venv .venv
source .venv/bin/activate  # En Windows: .venv\Scripts\activate
pip install -e .
media-organizer --source /ruta/origen --destination /ruta/destino --dry-run
```

### CLI

- `--profile` permite elegir un template predefinido (`default`, `year_month_day`, `year_month_name`, `camera`).
- `--template` acepta un formato personalizado que se interpreta dentro de la categoría (p. ej. `"{year}/{month_name}"`).
- `--extra clave=valor` agrega variables adicionales para usar en templates (requiere nombrarlas en el template).
- `--dry-run` muestra el plan sin mover archivos.
- Al finalizar, se muestran tablas con el detalle de cada archivo, un resumen por estado y otro por categoría.
- Placeholders adicionales disponibles: `{category}`, `{category_label}`, `{category_slug}`.

Ejemplo:

```bash
media-organizer \
  --source ~/Media \
  --destination /mnt/organizado \
  --profile year_month_name \
  --dry-run
```

El ejemplo anterior generará rutas como:

- `Fotos_y_Videos/2023/mayo/...`
- `Musica/2020/julio/...`
- `Documentos/2019/12/...`
- `Otros/unknown_date/...`

Puedes añadir perfiles personalizados en un YAML (ver `profiles.sample.yaml`) y cargarlos con `--profiles-path`.

Los archivos que no tengan una fecha de captura confiable se agrupan en `unknown_date/` dentro de su categoría para que puedas revisarlos manualmente.

## Notas sobre HEIC

El paquete incluye `pillow-heif`. En caso de que la librería no esté disponible en tu entorno, el programa seguirá funcionando, pero los archivos HEIC se procesarán con capacidades reducidas.

## Empaquetado

Se recomiendan herramientas como PyInstaller o Briefcase para generar ejecutables nativos. Las recetas específicas se documentarán una vez integrado el flujo de build.

Ejemplo básico con PyInstaller (desde un entorno virtual):

```bash
pyinstaller --name media-organizer --onefile -p src media_organizer/cli.py
```

## Pruebas

```bash
pytest
```
