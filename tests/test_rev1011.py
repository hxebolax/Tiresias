"""Pruebas de regresión de la versión 1.0.11 (auditoría): cursor braille y actualización portable.

- Con liblouis, el cursor detrás del último carácter queda detrás de la última
  celda (antes aparecía en la celda 0 o 1 y la línea saltaba al principio).
- La actualización de la copia portable prepara la versión nueva aparte y
  sustituye con renombrados: si se interrumpe mientras prepara, la copia que
  funciona no se toca; al terminar no quedan carpetas de trabajo.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_rev1011 -v``
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import installer  # noqa: E402
from tiresias.braille import liblouis, tables  # noqa: E402


@unittest.skipUnless(liblouis.load(), "liblouis no está disponible")
class CursorBrailleTests(unittest.TestCase):
	def test_cursor_al_final_de_la_linea(self) -> None:
		for name in ("Es-Es-G0.utb", "es-g1.ctb", "es-g2.ctb"):
			table = tables.getTable(name)
			for text in ("Casa 123", "Editar: hola mundo", "x", "Hola 😀"):
				tr = tables.translate(table, text, len(text), expandAtCursor=True)
				self.assertEqual(tr.cursorPos, len(tr.cells), (name, text))

	def test_cursor_dentro_de_la_linea(self) -> None:
		table = tables.getTable("Es-Es-G0.utb")
		tr = tables.translate(table, "Casa 123", 4, expandAtCursor=True)
		self.assertEqual(tr.cursorPos, 4)
		tr = tables.translate(table, "Casa 123", 0, expandAtCursor=True)
		self.assertEqual(tr.cursorPos, 0)


class ActualizacionPortableTests(unittest.TestCase):
	def setUp(self) -> None:
		self.tmp = tempfile.mkdtemp(prefix="tiresias_rev1011_")
		self.old = os.path.join(self.tmp, "vieja")
		self.new = os.path.join(self.tmp, "nueva")
		self.files(self.old, {"Tiresias.exe": "viejo", "lib/viejo.pyc": "x", "data/config/config.json": "{}", "data/locale/es.mo": "viejo"})
		self.files(self.new, {"Tiresias.exe": "nuevo", "lib/nuevo.pyc": "x", "data/locale/es.mo": "nuevo"})

	def tearDown(self) -> None:
		shutil.rmtree(self.tmp, ignore_errors=True)

	@staticmethod
	def files(base: str, mapping: dict[str, str]) -> None:
		for rel, text in mapping.items():
			p = os.path.join(base, *rel.split("/"))
			os.makedirs(os.path.dirname(p), exist_ok=True)
			with open(p, "w", encoding="utf-8") as f:
				f.write(text)

	def read(self, rel: str) -> str:
		with open(os.path.join(self.old, *rel.split("/")), encoding="utf-8") as f:
			return f.read()

	def test_sin_carpetas_de_trabajo_al_terminar(self) -> None:
		installer.applyPortableUpdate(self.new, self.old)
		self.assertEqual(self.read("Tiresias.exe"), "nuevo")
		self.assertEqual(self.read("data/locale/es.mo"), "nuevo")
		for d in (installer.UPDATE_BACKUP_DIR, installer.UPDATE_STAGING_DIR):
			self.assertFalse(os.path.exists(os.path.join(self.old, d)), d)

	def test_interrupcion_al_preparar_no_toca_la_copia(self) -> None:
		def interrupted(src, dst, *a, **kw):
			# Simula que el proceso muere mientras copia a la carpeta de preparación.
			raise KeyboardInterrupt

		with mock.patch.object(installer, "copyTree", side_effect=interrupted), self.assertRaises(KeyboardInterrupt):
			installer.applyPortableUpdate(self.new, self.old)
		# La copia que funciona sigue entera: no se ha movido nada a la copia de seguridad.
		self.assertEqual(self.read("Tiresias.exe"), "viejo")
		self.assertTrue(os.path.isfile(os.path.join(self.old, "lib", "viejo.pyc")))
		self.assertEqual(self.read("data/locale/es.mo"), "viejo")
		self.assertFalse(os.path.exists(os.path.join(self.old, installer.UPDATE_BACKUP_DIR)))

	def test_fallo_al_sustituir_restaura(self) -> None:
		real = os.replace
		calls = [0]

		def failing(src, dst):
			# Falla al colocar lo nuevo (después de apartar lo antiguo).
			if installer.UPDATE_STAGING_DIR in str(src):
				calls[0] += 1
				if calls[0] == 2:
					raise OSError("acceso denegado")
			return real(src, dst)

		with mock.patch.object(installer.os, "replace", side_effect=failing), self.assertRaises(OSError):
			installer.applyPortableUpdate(self.new, self.old)
		self.assertEqual(self.read("Tiresias.exe"), "viejo")
		self.assertTrue(os.path.isfile(os.path.join(self.old, "lib", "viejo.pyc")))
		self.assertFalse(os.path.exists(os.path.join(self.old, "lib", "nuevo.pyc")))
		self.assertEqual(self.read("data/locale/es.mo"), "viejo")
		for d in (installer.UPDATE_BACKUP_DIR, installer.UPDATE_STAGING_DIR):
			self.assertFalse(os.path.exists(os.path.join(self.old, d)), d)

	def test_copia_de_seguridad_anterior_se_conserva(self) -> None:
		self.files(self.old, {installer.UPDATE_BACKUP_DIR + "/lib/unico.pyc": "rescatar"})
		installer.applyPortableUpdate(self.new, self.old)
		kept = [d for d in os.listdir(self.old) if d.startswith(installer.UPDATE_BACKUP_DIR + "_")]
		self.assertEqual(len(kept), 1)
		self.assertTrue(os.path.isfile(os.path.join(self.old, kept[0], "lib", "unico.pyc")))


if __name__ == "__main__":
	unittest.main()
