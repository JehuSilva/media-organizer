# Media Organizer

Automatic photo and video organizer with configurable destination templates.

## Características

- Extrae metadatos (EXIF, fecha de creación) para ordenar archivos multimedia.
- Plantillas configurables para organizar por año, mes, día u otros atributos.
- Modo `dry-run` para validar resultados sin mover archivos.
- Soporte para HEIC mediante `pillow-heif` y compatibilidad básica con videos usando `ffprobe`.
- Archivos sin fecha confiable se ubican automáticamente en `unknown_date/`.
- Empaquetado multiplataforma mediante PyInstaller (scripts incluidos posteriormente).

## Requisitos

- Python 3.10 o superior.
- [FFmpeg](https://ffmpeg.org/) instalado y disponible en el `PATH` si se desea extraer metadatos precisos de videos.

## Uso rápido

```bash
python -m venv .venv
source .venv/bin/activate  # En Windows: .venv\Scripts\activate
pip install -e .
media-organizer --source /ruta/origen --destination /ruta/destino --dry-run
```

### CLI

- `--profile` permite elegir un template predefinido (`default`, `year_month_day`, `year_month_name`, `camera`).
- `--template` acepta un formato personalizado, por ejemplo `"{year}/{month:02d}/{evento}"`.
- `--extra clave=valor` agrega variables adicionales para usar en templates (requiere nombrarlas en el template).
- `--dry-run` muestra el plan sin mover archivos.
- Al finalizar, se muestran tablas con el detalle de cada archivo y un resumen por estado.

Ejemplo:

```bash
media-organizer \
  --source ~/DCIM \
  --destination /mnt/fotos/ordenadas \
  --profile year_month_name \
  --dry-run
```

Puedes añadir perfiles personalizados en un YAML (ver `profiles.sample.yaml`) y cargarlos con `--profiles-path`.

Los archivos que no tengan una fecha de captura confiable se agrupan en la carpeta `unknown_date/` para que puedas revisarlos manualmente.

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
