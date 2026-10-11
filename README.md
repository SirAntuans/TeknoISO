# 📀 TeknoISO

> Utilidad **freeware** para crear imágenes ISO a partir de discos CD/DVD.
> Ligera, portable y fácil de usar. Desarrollada por **APSoft**.

![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![Licencia](https://img.shields.io/badge/Licencia-MIT-green)
![Plataformas](https://img.shields.io/badge/Plataformas-Windows%20%7C%20Linux-lightgrey)
![Release](https://img.shields.io/badge/Ejecutable-compilado%20autom%C3%A1ticamente-orange)

## ✨ Características

- **Sin dependencias**: solo biblioteca estándar de Python (tkinter y ctypes).
- **Detección automática** de unidades de CD/DVD.
- **Lectura sector a sector**: la imagen ISO/UDF resultante es válida, montable y grabable con cualquier software.
- **Progreso en tiempo real**: porcentaje, velocidad y tiempo restante estimado.
- **Suma SHA-256 opcional** para verificar copias idénticas.
- **Ejecutable portable para Windows** compilado automáticamente en cada versión.

## 📥 Descargar el ejecutable

Descarga **TeknoISO-windows-x64.zip** desde [Releases](../../releases), descomprímelo y ejecuta `TeknoISO.exe`. No requiere instalación.

## 🖥️ Uso

1. Inserta el disco de datos en la unidad.
2. Ejecuta TeknoISO y selecciona la unidad.
3. Elige dónde guardar el archivo `.iso`.
4. Pulsa **Crear imagen ISO** y espera a que termine.

> 💡 TeknoISO está pensado para **discos de datos** (ISO 9660 / UDF). Los CD de audio requieren extracción digital (CDDA), que es un proceso distinto.

## 📦 Ejecutar desde el código fuente

```bash
python tekno_iso.py
```

Requiere Python 3.8+ con tkinter. En Linux se necesitan permisos de lectura de la unidad: `sudo` o pertenecer al grupo `cdrom`.

## 🔨 Compilar tu propio ejecutable

```bash
pip install pyinstaller
python assets/make_icon.py     # genera el icono assets/TeknoISO.ico
pyinstaller TeknoISO.spec       # ejecutable de un solo archivo, con icono
```

El ejecutable queda en la carpeta `dist/`. El icono se genera con código puro de Python (sin herramientas de dibujo); ver `assets/make_icon.py`.

O simplemente publica una Release: GitHub Actions genera el icono, compila y adjunta el `.exe` automáticamente (ver `.github/workflows/build.yml`).

## 🤝 Contribuir

Las contribuciones son bienvenidas: errores, ideas y traducciones.

- ¿Encontraste un fallo? Abre un issue con la plantilla **🐞 Reporte de error**.
- ¿Tienes una idea? Usa la plantilla **💡 Sugerencia de mejora**.

## 📄 Licencia

[MIT](LICENSE) — uso, modificación y distribución libres. Freeware.
