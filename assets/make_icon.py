#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Genera el icono de TeknoISO (assets/TeknoISO.ico) sin dependencias.

Dibuja un disco óptico sobre un rectángulo redondeado con degradado,
lo codifica como PNG y lo empaqueta en un contenedor .ico (formato
PNG embebido, compatible con Windows Vista o superior).

Se ejecuta automáticamente en la compilación de GitHub Actions.

Uso:  python assets/make_icon.py
"""

import math
import os
import struct
import zlib

TAM = 256                 # tamaño del icono (256x256)
CARPETA = os.path.dirname(os.path.abspath(__file__))

# ----------------------------------------------------------------------
# Paleta
BG_ARRIBA = (30, 110, 224)     # azul Tekno
BG_ABAJO = (14, 70, 156)
DISCO_CENTRO = (245, 248, 252)
DISCO_BORDE = (160, 172, 190)


def clamp(v, inferior=0.0, superior=1.0):
    return max(inferior, min(superior, v))


def lerp(c1, c2, t):
    return tuple(int(round(a + (b - a) * t)) for a, b in zip(c1, c2))


def sd_rect_redondeado(x, y, cx, cy, ancho, alto, radio):
    """Distancia con signo a un rectángulo redondeado (negativa dentro)."""
    qx = abs(x - cx) - (ancho / 2 - radio)
    qy = abs(y - cy) - (alto / 2 - radio)
    fuera = math.hypot(max(qx, 0.0), max(qy, 0.0))
    dentro = min(max(qx, qy), 0.0)
    return fuera + dentro - radio


def color_pixel(x, y):
    cx = cy = (TAM - 1) / 2.0

    # --- Fondo: rectángulo redondeado con degradado vertical
    d_bg = sd_rect_redondeado(x, y, cx, cy, 244, 244, 46)
    cob_bg = clamp(0.5 - d_bg)              # cobertura con antialias
    color_bg = lerp(BG_ARRIBA, BG_ABAJO, y / (TAM - 1.0))

    # --- Disco óptico
    d = math.hypot(x - cx, y - cy)
    cob_disco = clamp(74.5 - d)
    t = clamp(d / 74.0)
    color = lerp(DISCO_CENTRO, DISCO_BORDE, t)

    # Brillo superior sutil
    if y < cy:
        color = lerp(color, (255, 255, 255), clamp((cy - y) / 74.0) * 0.22)

    # Anillos del disco
    if 55.0 <= d <= 59.0:
        color = lerp(color, (120, 132, 150), 0.55)
    if 28.0 <= d <= 31.0:
        color = lerp(color, (205, 212, 224), 0.5)

    # Componer disco sobre fondo
    color = lerp(color_bg, color, cob_disco)

    # Agujero central: deja ver el fondo
    dentro_hueco = clamp(13.5 - d)
    color = lerp(color, color_bg, dentro_hueco)

    return (color[0], color[1], color[2], int(cob_bg * 255))


def generar_png(ruta, tam):
    """Escribe un PNG RGBA de tam x tam, píxel a píxel (solo stdlib)."""
    filas = bytearray()
    for y in range(tam):
        filas.append(0)                       # filtro: ninguno
        for x in range(tam):
            filas += bytes(color_pixel(x, y))
    comprimido = zlib.compress(bytes(filas), 9)

    def trozo(tipo, datos):
        bloque = struct.pack(">I", len(datos)) + tipo + datos
        return bloque + struct.pack(">I", zlib.crc32(tipo + datos) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", tam, tam, 8, 6, 0, 0, 0)   # RGBA 8 bits
    with open(ruta, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(trozo(b"IHDR", ihdr))
        f.write(trozo(b"IDAT", comprimido))
        f.write(trozo(b"IEND", b""))


def generar_ico(ruta_ico, ruta_png):
    """Empaqueta el PNG en un contenedor .ico (PNG embebido, Windows Vista+)."""
    with open(ruta_png, "rb") as f:
        png = f.read()
    cabecera = struct.pack("<HHH", 0, 1, 1)                   # ico, 1 imagen
    entrada = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png), 22)
    with open(ruta_ico, "wb") as f:
        f.write(cabecera + entrada + png)


def main():
    vista_previa = os.path.join(CARPETA, "icono_preview.png")
    icono = os.path.join(CARPETA, "TeknoISO.ico")
    generar_png(vista_previa, TAM)
    generar_ico(icono, vista_previa)
    print(f"Icono generado: {icono}")
    print(f"Vista previa:   {vista_previa}")


if __name__ == "__main__":
    main()
