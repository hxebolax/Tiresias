"""Copias de seguridad de zUtilidades (archivos ``.zut-zl`` y ``.zut-zn``).

Igual que en el complemento original, una copia es un ZIP con la carpeta del
módulo (``zLauncher/...`` o ``zNotes/...``) y, como comentario del ZIP, la
firma MD5 de la lista de archivos que contiene. Si la firma no coincide la
copia no se restaura.

Se pueden restaurar también las copias hechas con el complemento de NVDA
(con ``index.dat`` y archivos ``.dat``): se convierten al formato de Tiresias.

Este módulo no usa wx. ``progreso(porcentaje, texto)`` se llama desde el hilo
que hace la copia.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
import zipfile
from typing import Callable

from . import datos

EXTENSIONES = {datos.LANZADOR: ".zut-zl", datos.NOTAS: ".zut-zn"}

Progreso = Callable[[int, str], None]


def nombrePorDefecto() -> str:
	"""``Backup-ddmmaaaahhmmss`` (sin extensión), como el original."""
	return "Backup-" + time.strftime("%d%m%Y%H%M%S")


def _md5(texto: bytes) -> str:
	return hashlib.md5(texto).hexdigest()


def _listaZip(archivo: str) -> bytes:
	with zipfile.ZipFile(archivo, "r") as z:
		return "-".join(z.namelist()).encode("utf-8")


def _leerComentario(archivo: str) -> str:
	with zipfile.ZipFile(archivo, "r") as z:
		return z.comment.decode("utf-8", "replace")


def firmaValida(archivo: str) -> bool:
	"""¿El comentario del ZIP coincide con la firma de su lista de archivos?"""
	try:
		return _md5(_listaZip(archivo)) == _leerComentario(archivo)
	except (OSError, zipfile.BadZipFile, ValueError):
		return False


def _nada(p: int, t: str) -> None:
	pass


def hacerCopia(modulo: str, destino: str, progreso: Progreso = _nada) -> None:
	"""Comprime la base de datos de ``modulo`` en ``destino`` y la firma.

	Si algo falla se borra el archivo a medio hacer y se lanza la excepción.
	"""
	carpeta = datos.moduloDir(modulo)
	base = os.path.basename(carpeta)
	archivos = []
	for root, _dirs, files in os.walk(carpeta):
		for fn in sorted(files):
			if fn.endswith(".tmp"):
				continue
			archivos.append(os.path.join(root, fn))
	total = sum(os.path.getsize(p) for p in archivos) or 1
	hecho = 0
	try:
		with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
			for path in archivos:
				fn = os.path.basename(path)
				progreso(int(100 * hecho / total), "Comprimiendo el archivo: %s" % fn)
				z.write(path, base + "/" + fn)
				hecho += os.path.getsize(path)
		firma = _md5(_listaZip(destino))
		with zipfile.ZipFile(destino, "a") as z:
			z.comment = firma.encode("utf-8")
		if not firmaValida(destino):
			raise ValueError("La firma de la copia no coincide")
		progreso(100, "")
	except BaseException:
		try:
			os.remove(destino)
		except OSError:
			pass
		raise


def _miembrosSeguros(z: zipfile.ZipFile, modulo: str) -> list[zipfile.ZipInfo]:
	"""Miembros ``<modulo>/<archivo>`` sin rutas raras (evita escribir fuera)."""
	res = []
	for info in z.infolist():
		nombre = info.filename.replace("\\", "/")
		if info.is_dir():
			continue
		partes = nombre.split("/")
		if len(partes) != 2 or partes[0] != modulo or not partes[1] or partes[1] in (".", ".."):
			raise ValueError("La copia no es de este módulo o tiene rutas no válidas")
		if ":" in partes[1]:
			raise ValueError("Ruta no válida en la copia")
		res.append(info)
	if not res:
		raise ValueError("La copia está vacía")
	return res


def restaurarCopia(modulo: str, origen: str, progreso: Progreso = _nada) -> int:
	"""Sustituye la base de datos de ``modulo`` por la copia ``origen``.

	Devuelve el número de categorías restauradas. Si la copia no es válida
	lanza ``ValueError`` sin tocar la base de datos actual.
	"""
	if not firmaValida(origen):
		raise ValueError("La firma de la copia no coincide")
	destinoFinal = datos.moduloDir(modulo)
	tmp = tempfile.mkdtemp(prefix="zut_", dir=datos.baseDir())
	try:
		with zipfile.ZipFile(origen) as z:
			miembros = _miembrosSeguros(z, modulo)
			total = sum(m.file_size for m in miembros) or 1
			hecho = 0
			carpeta = os.path.join(tmp, modulo)
			os.makedirs(carpeta, exist_ok=True)
			for m in miembros:
				fn = m.filename.replace("\\", "/").split("/")[1]
				hecho += m.file_size
				progreso(int(100 * hecho / total), "Descomprimiendo el archivo: %s" % fn)
				with z.open(m) as src, open(os.path.join(carpeta, fn), "wb") as dst:
					shutil.copyfileobj(src, dst)
		nombres = os.listdir(carpeta)
		if datos.INDICE in nombres:
			pass
		elif "index.dat" in nombres:
			# Copia hecha con el complemento de NVDA.
			datos.convertirDesdeNVDA(carpeta)
		else:
			raise ValueError("La copia no tiene índice")
		# Comprobación: el índice se puede leer.
		with open(os.path.join(carpeta, datos.INDICE), encoding="utf-8") as f:
			indice = json.load(f)
		if not isinstance(indice, dict) or not isinstance(indice.get("categorias"), list):
			raise ValueError("Índice no válido")
		# Se sustituye el contenido de la carpeta del módulo.
		shutil.rmtree(destinoFinal, ignore_errors=True)
		os.makedirs(destinoFinal, exist_ok=True)
		for fn in os.listdir(destinoFinal):
			p = os.path.join(destinoFinal, fn)
			if os.path.isfile(p):
				os.remove(p)
		for fn in os.listdir(carpeta):
			shutil.copy2(os.path.join(carpeta, fn), os.path.join(destinoFinal, fn))
		progreso(100, "")
		return len(indice["categorias"])
	finally:
		shutil.rmtree(tmp, ignore_errors=True)
