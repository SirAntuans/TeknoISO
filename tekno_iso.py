#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TeknoISO 1.0.1 — Crea imágenes ISO a partir de discos CD/DVD (freeware).

Características:
- Sin dependencias externas: solo biblioteca estándar de Python (tkinter, ctypes).
- Detecta automáticamente las unidades ópticas del equipo.
- Lee el disco sector a sector: el resultado es una imagen ISO/UDF válida
  (montable y grabable con cualquier software).
- Reintenta lecturas fallidas y recupera los sectores finales uno a uno.
- Verifica la completitud ISO 9660 del resultado: si falta solo lead-out
  o sectores no grabados, la imagen se declara completa.
- Barra de progreso con porcentaje, velocidad y tiempo restante estimado.
- Suma de verificación SHA-256 opcional al vuelo.
- Funciona en Windows (lectura en crudo \\\\.\\X:) y en Linux (/dev/srX).

Requisitos: Python 3.8 o superior con tkinter.
En Linux: ejecutar con sudo o pertenecer al grupo 'cdrom'.
Nota: pensado para discos de DATOS (ISO 9660 / UDF). Los CD de audio
requieren extracción digital (CDDA), que es un proceso distinto.
"""

import ctypes
import errno
import glob
import hashlib
import os
import queue
import shutil
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

ES_WINDOWS = os.name == "nt"
SECTOR = 2048
BLOQUE = SECTOR * 512            # 1 MiB por lectura
IOCTL_DISK_GET_LENGTH_INFO = 0x0007405C


# --------------------------------------------------------------------------
# Utilidades de formato
# --------------------------------------------------------------------------

def formato_bytes(n):
    n = float(n)
    for unidad in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or unidad == "TiB":
            if unidad == "B":
                return f"{int(n)} B"
            return f"{n:,.2f} {unidad}".replace(",", " ")
        n /= 1024


def formato_tiempo(segundos):
    segundos = max(0, int(segundos))
    if segundos < 60:
        return f"{segundos} s"
    minutos, seg = divmod(segundos, 60)
    if minutos < 60:
        return f"{minutos} min {seg:02d} s"
    horas, minutos = divmod(minutos, 60)
    return f"{horas} h {minutos:02d} min"


def nombre_seguro(texto):
    for ch in '<>:"/\\|?*':
        texto = texto.replace(ch, "_")
    return texto.strip() or "disco"


# --------------------------------------------------------------------------
# Detección de unidades y tamaño del disco — backend Windows
# --------------------------------------------------------------------------

_kernel32 = None


def _kernel():
    global _kernel32
    if _kernel32 is None:
        k = ctypes.windll.kernel32
        k.GetLogicalDrives.restype = ctypes.c_uint32
        k.CreateFileW.restype = ctypes.c_void_p
        k.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32,
                                  ctypes.c_uint32, ctypes.c_void_p,
                                  ctypes.c_uint32, ctypes.c_uint32,
                                  ctypes.c_void_p]
        k.CloseHandle.argtypes = [ctypes.c_void_p]
        k.DeviceIoControl.restype = ctypes.c_int
        k.DeviceIoControl.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                      ctypes.c_void_p, ctypes.c_uint32,
                                      ctypes.c_void_p, ctypes.c_uint32,
                                      ctypes.c_void_p, ctypes.c_void_p]
        _kernel32 = k
    return _kernel32


def unidades_windows():
    """Devuelve la lista de unidades ópticas con etiqueta del disco."""
    k = _kernel()
    resultado = []
    mascara = k.GetLogicalDrives()
    for i in range(26):
        if not (mascara & (1 << i)):
            continue
        letra = chr(65 + i)
        if k.GetDriveTypeW(f"{letra}:\\") != 5:      # 5 = DRIVE_CDROM
            continue
        etiqueta = ""
        b_etiqueta = ctypes.create_unicode_buffer(261)
        b_fs = ctypes.create_unicode_buffer(261)
        if k.GetVolumeInformationW(f"{letra}:\\", b_etiqueta, 261, None, None,
                                   None, b_fs, 261):
            etiqueta = b_etiqueta.value
        resultado.append({
            "ruta": f"\\\\.\\{letra}:",
            "nombre": f"{letra}:  {etiqueta or '(sin disco)'}",
            "etiqueta": etiqueta,
        })
    return resultado


def tamano_windows(ruta):
    """Tamaño en bytes del disco insertado (None si no se puede saber)."""
    k = _kernel()
    INVALIDO = ctypes.c_void_p(-1).value
    GENERIC_READ, OPEN_EXISTING, FILE_SHARE_READ = 0x80000000, 3, 1
    handle = k.CreateFileW(ruta, GENERIC_READ, FILE_SHARE_READ, None,
                           OPEN_EXISTING, 0, None)
    if not handle or handle == INVALIDO:
        return None
    try:
        bufer = ctypes.c_ulonglong(0)
        if k.DeviceIoControl(handle, IOCTL_DISK_GET_LENGTH_INFO, None, 0,
                             ctypes.byref(bufer), ctypes.sizeof(bufer),
                             None, None):
            return bufer.value
    finally:
        k.CloseHandle(handle)
    return None


# --------------------------------------------------------------------------
# Backend Linux
# --------------------------------------------------------------------------

def unidades_linux():
    vistas = {}
    for patron in ("/dev/sr*", "/dev/cdrom*"):
        for ruta in sorted(glob.glob(patron)):
            real = os.path.realpath(ruta)
            if os.path.exists(real) and real not in vistas:
                vistas[real] = {"ruta": real, "nombre": real, "etiqueta": ""}
    return list(vistas.values())


def tamano_linux(ruta):
    try:
        with open(f"/sys/block/{os.path.basename(ruta)}/size") as f:
            return int(f.read().strip()) * 512
    except Exception:
        return None


if ES_WINDOWS:
    listar_unidades = unidades_windows
    obtener_tamano = tamano_windows
else:
    listar_unidades = unidades_linux
    obtener_tamano = tamano_linux


# --------------------------------------------------------------------------
# Volcado del disco (hilo de trabajo)
# --------------------------------------------------------------------------

def _leer_fd(descriptor, cantidad, reintentos=3, pausa=0.25, err=None):
    """Lee del descriptor con reintentos. Devuelve (datos, fallo).

    En medios ópticos una lectura puede fallar por un error puntual y
    tener éxito al reintentarla; por eso no nos rendimos a la primera.
    Si se pasa una lista `err`, se deposita ahí el último OSError para
    poder informarlo al usuario.
    """
    for intento in range(reintentos):
        try:
            datos = os.read(descriptor, cantidad)
            return (datos or b""), False    # b"" = EOF limpio, no es error
        except PermissionError:
            raise                           # reintentar no ayuda
        except OSError as e:
            if err is not None:
                err.append(e)
            if intento == reintentos - 1:
                return None, True
            time.sleep(pausa)
    return None, True


def comprobar_iso9660(destino, leidos):
    """True si la imagen captura el volumen ISO 9660 completo.

    El descriptor de volumen primario (PVD) del sector 16 declara el
    tamaño real del volumen de datos. Si ya se copió todo él, la
    diferencia respecto al tamaño físico del disco son sectores de
    lead-out o no grabados, que no forman parte de los datos.
    """
    try:
        with open(destino, "rb") as f:
            f.seek(16 * SECTOR)
            pvd = f.read(SECTOR)
        if len(pvd) < SECTOR or pvd[0:1] != b"\x01" or pvd[1:6] != b"CD001":
            return False                                   # no es ISO 9660
        tam_volumen = int.from_bytes(pvd[80:84], "little") * SECTOR
        return leidos >= tam_volumen
    except Exception:
        return False


def volcar(origen, destino, total, cola, evento_cancelar, con_sha256):
    """Copia el dispositivo completo a un archivo ISO. Reporta progreso."""
    leidos = 0
    digest = hashlib.sha256() if con_sha256 else None
    inicio = time.monotonic()
    ok = False
    mensaje = ""
    errores_lectura = []
    try:
        descriptor = os.open(origen, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        try:
            with open(destino, "wb") as dst:
                while not evento_cancelar.is_set():
                    if total and leidos >= total:
                        break
                    a_leer = BLOQUE if not total else min(BLOQUE, total - leidos)
                    datos, fallo = _leer_fd(descriptor, a_leer,
                                            err=errores_lectura)
                    if fallo or not datos:
                        # Fin de los datos o error de lectura: con tamaño
                        # conocido, intentar recuperar sector a sector los
                        # restantes antes de darse por vencido.
                        if total and leidos < total:
                            for _ in range(64):            # hasta 128 KiB extra
                                if evento_cancelar.is_set():
                                    break
                                sector, fallo_sector = _leer_fd(
                                    descriptor, SECTOR, reintentos=3, pausa=0.1,
                                    err=errores_lectura)
                                if fallo_sector or not sector:
                                    break
                                dst.write(sector)
                                if digest:
                                    digest.update(sector)
                                leidos += len(sector)
                                cola.put(("progreso", leidos, total,
                                          leidos / max(time.monotonic() - inicio, 1e-6)))
                        break
                    dst.write(datos)
                    if digest:
                        digest.update(datos)
                    leidos += len(datos)
                    transcurrido = max(time.monotonic() - inicio, 1e-6)
                    cola.put(("progreso", leidos, total, leidos / transcurrido))
        finally:
            os.close(descriptor)

        if evento_cancelar.is_set():
            mensaje = ("Cancelado: la imagen quedó INCOMPLETA y no debe usarse. "
                       f"Se copiaron {formato_bytes(leidos)}.")
        elif total and leidos < total:
            if comprobar_iso9660(destino, leidos):
                ok = True
                duracion = formato_tiempo(time.monotonic() - inicio)
                mensaje = (f"Imagen creada: {formato_bytes(leidos)}. El disco "
                           f"reporta {formato_bytes(total)}, pero los sectores "
                           "restantes son de lead-out o no grabados: el sistema "
                           f"de archivos ISO 9660 está completo. Duración: {duracion}.")
            else:
                faltan = formato_bytes(total - leidos)
                detalle = f" — {errores_lectura[-1]}" if errores_lectura else ""
                mensaje = (f"Atención: solo se copiaron {formato_bytes(leidos)} de "
                           f"{formato_bytes(total)} ({faltan} ilegibles{detalle}). "
                           "La imagen quedó INCOMPLETA: limpia el disco o revisa la unidad.")
        else:
            ok = True
            duracion = formato_tiempo(time.monotonic() - inicio)
            mensaje = f"Imagen creada correctamente: {formato_bytes(leidos)} en {duracion}."
    except PermissionError:
        mensaje = ("Sin permisos para leer la unidad. "
                   "En Linux ejecuta con sudo o añádete al grupo 'cdrom'.")
    except OSError as e:
        if e.errno == errno.ENOSPC:
            mensaje = ("Espacio insuficiente en el disco de destino mientras se "
                       "escribía la imagen. Libera espacio e inténtalo de nuevo.")
        else:
            mensaje = (f"Error de E/S: {e}. Comprueba que hay un disco insertado "
                       "y que la unidad responde.")
    except Exception as e:
        mensaje = f"Error inesperado: {e}"
    finally:
        resumen = digest.hexdigest() if (digest and ok) else None
        cola.put(("fin", ok, mensaje, resumen))


# --------------------------------------------------------------------------
# Interfaz gráfica
# --------------------------------------------------------------------------

class Aplicacion:

    def __init__(self, raiz):
        self.raiz = raiz
        self.unidades = []
        self.cola = queue.Queue()
        self.cancelar = threading.Event()
        self.hilo = None
        self.trabajando = False
        self._montar()
        self.refrescar()
        self._sondear()

    # ---------------------------------------------------------------- UI

    def _montar(self):
        self.raiz.title("TeknoISO — Crea imágenes ISO de CD y DVD (APSoft)")
        self.raiz.minsize(600, 460)

        marco = ttk.Frame(self.raiz, padding=14)
        marco.grid(row=0, column=0, sticky="nsew")
        self.raiz.columnconfigure(0, weight=1)
        self.raiz.rowconfigure(0, weight=1)
        marco.columnconfigure(1, weight=1)

        negrita = ("", 10, "bold")

        # --- Unidad de disco
        ttk.Label(marco, text="Unidad de disco:", font=negrita)\
            .grid(row=0, column=0, sticky="w", pady=4)
        self.cmb_unidad = ttk.Combobox(marco, state="readonly")
        self.cmb_unidad.grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        self.cmb_unidad.bind("<<ComboboxSelected>>", self._al_cambiar_unidad)
        self.btn_refrescar = ttk.Button(marco, text="Actualizar", width=10,
                                        command=self.refrescar)
        self.btn_refrescar.grid(row=0, column=2, pady=4)

        # --- Archivo de destino
        ttk.Label(marco, text="Imagen ISO destino:", font=negrita)\
            .grid(row=1, column=0, sticky="w", pady=4)
        self.ent_destino = ttk.Entry(marco)
        self.ent_destino.grid(row=1, column=1, sticky="ew", padx=6, pady=4)
        self.btn_examinar = ttk.Button(marco, text="Examinar…", width=10,
                                       command=self.examinar)
        self.btn_examinar.grid(row=1, column=2, pady=4)

        # --- Opciones
        self.var_sha = tk.BooleanVar(value=False)
        self.chk_sha = ttk.Checkbutton(
            marco, variable=self.var_sha,
            text="Calcular suma SHA-256 al terminar (para verificar copias)")
        self.chk_sha.grid(row=2, column=1, sticky="w", pady=2)

        # --- Botones de acción
        botones = ttk.Frame(marco)
        botones.grid(row=3, column=0, columnspan=3, sticky="e", pady=10)
        self.btn_crear = ttk.Button(botones, text="Crear imagen ISO",
                                    command=self.iniciar)
        self.btn_crear.configure(width=18)
        self.btn_crear.grid(row=0, column=0, padx=4)
        self.btn_cancelar = ttk.Button(botones, text="Cancelar", width=10,
                                       command=self._cancelar, state="disabled")
        self.btn_cancelar.grid(row=0, column=1, padx=4)

        # --- Progreso
        self.barra = ttk.Progressbar(marco, mode="determinate", maximum=100)
        self.barra.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(8, 2))
        self.var_estado = tk.StringVar(value="Listo. Inserta un disco y pulsa «Crear imagen ISO».")
        ttk.Label(marco, textvariable=self.var_estado).grid(
            row=5, column=0, columnspan=3, sticky="w")
        self.var_detalle = tk.StringVar(value="")
        ttk.Label(marco, textvariable=self.var_detalle, foreground="#555")\
            .grid(row=6, column=0, columnspan=3, sticky="w")

        # --- Registro
        ttk.Label(marco, text="Registro:", font=negrita)\
            .grid(row=7, column=0, sticky="w", pady=(12, 2))
        self.txt_log = tk.Text(marco, height=8, state="disabled", wrap="word",
                               background="#fafafa")
        self.txt_log.grid(row=8, column=0, columnspan=3, sticky="nsew", pady=2)
        marco.rowconfigure(8, weight=1)

        self._controles = [self.cmb_unidad, self.btn_refrescar,
                           self.ent_destino, self.btn_examinar,
                           self.chk_sha, self.btn_crear]

    # ------------------------------------------------------- acciones UI

    def refrescar(self):
        try:
            self.unidades = listar_unidades()
        except Exception as e:
            self.unidades = []
            self._log(f"No se pudieron listar las unidades: {e}")
        nombres = [u["nombre"] for u in self.unidades]
        self.cmb_unidad["values"] = nombres
        if nombres:
            self.cmb_unidad.current(0)
            self._al_cambiar_unidad()
        else:
            self.var_estado.set("No se detectaron unidades de CD/DVD en este equipo.")

    def _al_cambiar_unidad(self, *_):
        idx = self.cmb_unidad.current()
        if idx < 0 or idx >= len(self.unidades):
            return
        unidad = self.unidades[idx]
        if unidad["etiqueta"] and not self.ent_destino.get().strip():
            sugerido = nombre_seguro(unidad["etiqueta"]) + ".iso"
            self.ent_destino.insert(0, os.path.join(os.path.expanduser("~"),
                                                    "Desktop", sugerido))

    def examinar(self):
        inicial = os.path.basename(self.ent_destino.get().strip()) or "disco.iso"
        destino = filedialog.asksaveasfilename(
            title="Guardar imagen ISO como…",
            defaultextension=".iso",
            initialfile=inicial,
            filetypes=[("Imagen ISO", "*.iso"), ("Todos los archivos", "*.*")])
        if destino:
            self.ent_destino.delete(0, "end")
            self.ent_destino.insert(0, destino)

    def iniciar(self):
        if self.trabajando:
            return
        idx = self.cmb_unidad.current()
        if idx < 0 or idx >= len(self.unidades):
            messagebox.showwarning("Unidad", "Selecciona una unidad de disco.")
            return
        unidad = self.unidades[idx]
        destino = self.ent_destino.get().strip()
        if not destino:
            messagebox.showwarning("Destino", "Indica la ruta del archivo ISO de salida.")
            return
        if not destino.lower().endswith(".iso"):
            destino += ".iso"
            self.ent_destino.delete(0, "end")
            self.ent_destino.insert(0, destino)
        if os.path.exists(destino) and not messagebox.askyesno(
                "Sobrescribir", "El archivo ya existe.\n¿Deseas sobrescribirlo?"):
            return

        total = obtener_tamano(unidad["ruta"])
        if total:
            carpeta = os.path.dirname(os.path.abspath(destino)) or "."
            libre = shutil.disk_usage(carpeta).free
            if libre <= total:
                messagebox.showerror(
                    "Espacio insuficiente",
                    f"Se necesitan {formato_bytes(total)} y solo hay "
                    f"{formato_bytes(libre)} libres en el destino.")
                return
        os.makedirs(os.path.dirname(os.path.abspath(destino)), exist_ok=True)

        self.cancelar.clear()
        self.trabajando = True
        for control in self._controles:
            control.state(["disabled"])
        self.btn_cancelar.state(["!disabled"])
        self.barra.config(value=0)
        if total:
            self.barra.config(mode="determinate", maximum=total)
        else:
            self.barra.config(mode="indeterminate")
            self.barra.start(60)

        if total:
            self._log(f"Volcando {unidad['nombre']} → «{destino}» "
                      f"({formato_bytes(total)}, sector a sector)…")
        else:
            self._log(f"Volcando {unidad['nombre']} → «{destino}» "
                      f"(tamaño desconocido, leyendo hasta el final del disco)…")

        self.hilo = threading.Thread(
            target=volcar,
            args=(unidad["ruta"], destino, total, self.cola,
                  self.cancelar, self.var_sha.get()),
            daemon=True)
        self.hilo.start()

    def _cancelar(self):
        if self.trabajando:
            self.cancelar.set()
            self.btn_cancelar.state(["disabled"])
            self.var_estado.set("Cancelando… (se detendrá en unos segundos)")

    # ------------------------------------------------------- sondeo cola

    def _sondear(self):
        try:
            while True:
                mensaje = self.cola.get_nowait()
                if mensaje[0] == "progreso":
                    _, leidos, total, velocidad = mensaje
                    if total:
                        pct = leidos / total * 100
                        restante = (total - leidos) / max(velocidad, 1)
                        self.var_estado.set(f"Copiando… {pct:.1f}%")
                        self.var_detalle.set(
                            f"{formato_bytes(leidos)} de {formato_bytes(total)} · "
                            f"{formato_bytes(velocidad)}/s · "
                            f"faltan ~{formato_tiempo(restante)}")
                    else:
                        self.var_estado.set("Copiando…")
                        self.var_detalle.set(
                            f"{formato_bytes(leidos)} · {formato_bytes(velocidad)}/s")
                elif mensaje[0] == "fin":
                    self._al_terminar(mensaje[1], mensaje[2], mensaje[3])
        except queue.Empty:
            pass
        self.raiz.after(100, self._sondear)

    def _al_terminar(self, ok, mensaje, resumen_sha):
        self.trabajando = False
        self.barra.stop()
        self.barra.config(mode="determinate")
        for control in self._controles:
            control.state(["!disabled"])
        self.btn_cancelar.state(["disabled"])
        self.var_estado.set(mensaje)
        self.var_detalle.set("")
        self._log(mensaje)
        if resumen_sha:
            self._log(f"SHA-256: {resumen_sha}")
        if ok:
            messagebox.showinfo("Terminado", mensaje)
        else:
            messagebox.showerror("Problema", mensaje)

    # ---------------------------------------------------------------- log

    def _log(self, texto):
        self.txt_log.config(state="normal")
        self.txt_log.insert("end", time.strftime("[%H:%M:%S] ") + texto + "\n")
        self.txt_log.see("end")
        self.txt_log.config(state="disabled")


def main():
    raiz = tk.Tk()
    try:
        ttk.Style().theme_use("vista")       # aspecto nativo en Windows
    except tk.TclError:
        pass
    Aplicacion(raiz)
    raiz.mainloop()


if __name__ == "__main__":
    main()
