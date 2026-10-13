"""Pruebas de regresión de la versión 1.0.8.

- Al deletrear o leer un carácter, su nombre («dos puntos», «barra
  invertida») no se vuelve a procesar: antes se leía «dos espacio puntos».
- Los nombres de emojis y de símbolos desconocidos no se vuelven a procesar
  («bandera: España» no dice «bandera dos puntos España»).
- El indicador de lector de pantalla se cambia sin esperar a que todas las
  ventanas procesen el aviso (el arranque y el cierre tardaban 20 s).

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_rev108 -v``
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

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_rev108_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()
	paths._dataDirForTests = _TMP  # type: ignore[attr-defined]
else:
	_TMP = paths._dataDirForTests  # type: ignore[attr-defined]
	if not os.path.isdir(os.path.join(_TMP, "symbols")):
		shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))

from tiresias.config import conf  # noqa: E402
from tiresias.speech import api as speech  # noqa: E402
from tiresias.speech import symbols  # noqa: E402
from tiresias.speech.symbols import LEVEL_ALL, LEVEL_CHAR, LEVEL_MOST, SymbolProcessor  # noqa: E402


def _ensureSymbols() -> None:
	"""Otras pruebas de la batería cambian la carpeta de datos: se asegura la tabla de símbolos."""
	target = os.path.join(paths.DATA_DIR, "symbols")
	if not os.path.isfile(os.path.join(target, "es.json")):
		shutil.copytree(os.path.join(ROOT, "data", "symbols"), target, dirs_exist_ok=True)
	symbols._missing.clear()
	for proc in list(symbols._processors.values()):
		proc._loaded = False
	symbols.processor.language = "es"


def _spoken(text: str, language: str = "es") -> str:
	"""Lo que llega al sintetizador al deletrear ``text``."""
	seq = speech.getSpellingSequence(text, language=language)
	out = speech._processSequence(seq, LEVEL_CHAR)
	return " ".join(i.strip() for i in out if isinstance(i, str) and i.strip())


class TestDeletreo(unittest.TestCase):
	def setUp(self) -> None:
		_ensureSymbols()
		self.old = conf["speech"]["useSpellingFunctionality"]
		conf["speech"]["useSpellingFunctionality"] = False

	def tearDown(self) -> None:
		conf["speech"]["useSpellingFunctionality"] = self.old

	def test_dos_puntos_y_barra(self) -> None:
		self.assertEqual(_spoken(":"), "dos puntos")
		self.assertEqual(_spoken("\\"), "barra invertida")
		self.assertEqual(_spoken("¿"), "abre interrogación")

	def test_espacio_si_se_nombra(self) -> None:
		self.assertEqual(_spoken(" "), "espacio")

	def test_ruta_completa(self) -> None:
		said = _spoken(r"C:\Users")
		self.assertNotIn("espacio", said)
		self.assertIn("dos puntos", said)
		self.assertIn("barra invertida", said)

	def test_letras_de_dos_palabras(self) -> None:
		said = _spoken("w")
		self.assertNotIn("espacio", said)

	def test_ningun_nombre_de_la_tabla_lee_sus_espacios(self) -> None:
		for lang in ("es", "en"):
			proc = symbols.getProcessor(lang)
			self.assertIsNotNone(proc)
			for sym in proc.symbols:
				if len(sym) != 1 or sym.isspace():
					continue
				with self.subTest(lang=lang, sym=sym):
					# Se dice el nombre tal cual, sin «espacio» entre sus palabras.
					self.assertEqual(_spoken(sym, lang), proc.characterName(sym).strip())

	def test_descripcion_de_caracter_sin_espacios_leidos(self) -> None:
		seq = speech.getSpellingSequence("a", useCharacterDescriptions=True, language="es")
		out = speech._processSequence(seq, LEVEL_CHAR)
		said = " ".join(i for i in out if isinstance(i, str))
		self.assertNotIn("espacio", said)


class TestNombresNoReprocesados(unittest.TestCase):
	def setUp(self) -> None:
		_ensureSymbols()
		self.p = SymbolProcessor("es")

	def test_emoji_con_dos_puntos(self) -> None:
		out = self.p.process("\U0001F1EA\U0001F1F8 hola", LEVEL_MOST)
		self.assertIn("bandera: España", out)
		self.assertNotIn("dos puntos", out)

	def test_emoji_con_guion(self) -> None:
		out = self.p.process("\U0001F996", LEVEL_ALL)
		self.assertIn("T-rex", out)
		self.assertNotIn("guion", out)

	def test_resto_del_texto_sigue_procesandose(self) -> None:
		out = self.p.process("Hola: \U0001F996.", LEVEL_ALL)
		self.assertIn("dos puntos", out)
		self.assertIn("punto", out)
		self.assertIn("T-rex", out)

	def test_repeticiones(self) -> None:
		self.assertEqual(self.p.process("----- fin", LEVEL_ALL).strip(), "5 guion fin")

	def test_simbolo_desconocido(self) -> None:
		# \u00ab\u2296\u00bb: no est\u00e1 en la tabla ni es emoji; su nombre Unicode lleva espacios.
		self.assertNotIn("\u2296", self.p.symbols)
		out = self.p.process("a \u2296 b", LEVEL_ALL, unknownSymbols=True)
		self.assertIn("circled minus", out)
		self.assertNotIn("\U000F0000", out)

	def test_marcas_de_uso_privado_del_texto_se_respetan(self) -> None:
		# Un carácter del plano privado que ya viniera en el texto no se toca.
		out = self.p.process("x \U000F0000 \U0001F996", LEVEL_ALL)
		self.assertIn("T-rex", out)

	def test_separadores_numericos(self) -> None:
		out = self.p.process("son las 3:45 y 1.5", LEVEL_ALL)
		self.assertIn("3:45", out)
		self.assertIn("1.5", out)


class TestIndicadorLectorPantalla(unittest.TestCase):
	def test_sin_aviso_bloqueante(self) -> None:
		from tiresias.a11y import system

		calls = []
		fakeUser32 = mock.Mock()
		fakeUser32.SystemParametersInfoW.side_effect = lambda *a: calls.append(("spi", a)) or 1
		fakeUser32.SendNotifyMessageW.side_effect = lambda *a: calls.append(("notify", a)) or 1
		with mock.patch.object(system, "user32", fakeUser32):
			self.assertTrue(system.setScreenReaderFlag(True))
		spi = calls[0][1]
		self.assertEqual(spi[0], system.SPI_SETSCREENREADER)
		self.assertEqual(spi[1], 1)
		self.assertFalse(spi[3] & system.SPIF_SENDCHANGE)
		self.assertEqual(calls[1], ("notify", (system.HWND_BROADCAST, system.WM_SETTINGCHANGE, system.SPI_SETSCREENREADER, 0)))
		fakeUser32.SendMessageW.assert_not_called()
		fakeUser32.SendMessageTimeoutW.assert_not_called()


if __name__ == "__main__":
	unittest.main()
