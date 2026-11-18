"""Pruebas del complemento «Reloj para Tiresias» (complementos_tienda/RelojTiresias).

El complemento es de Guorco, hecho con ayuda de
IA. Se revisó para la tienda en la versión 1.6.3: tecla sin conflicto con
Tiresias, grabaciones sin duplicados y en la carpeta de datos, silencio en
espera y cuidado con el segundo sintetizador.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m pytest tests\\test_complemento_reloj.py -q``

Ninguna prueba suena ni toca el teclado: la voz y los sonidos se simulan.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
import wave
from datetime import datetime
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
ADDON = os.path.join(ROOT, "complementos_tienda", "RelojTiresias")
sys.path.insert(0, os.path.join(ADDON, "globalPlugins"))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_reloj_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()
	paths._dataDirForTests = _TMP  # type: ignore[attr-defined]
else:
	_TMP = paths._dataDirForTests  # type: ignore[attr-defined]

from tiresias.baseobject import normalizeGestureId  # noqa: E402
from tiresias.config import conf  # noqa: E402

_oldBytecode = sys.dont_write_bytecode
sys.dont_write_bytecode = True  # No deja __pycache__ en la carpeta del complemento.
import RelojTiresias as reloj  # noqa: E402

sys.dont_write_bytecode = _oldBytecode


class ManifiestoTests(unittest.TestCase):
	def test_autor_y_version(self) -> None:
		with open(os.path.join(ADDON, "manifest.json"), encoding="utf-8") as f:
			m = json.load(f)
		self.assertEqual(m["id"], "RelojTiresias")
		self.assertEqual(m["author"], "Guorco, con Mole")
		self.assertEqual(m["version"], "1.6.3")
		self.assertIn("Tiresias+Control+H", m["description"])
		self.assertNotIn("Tiresias+Control+R y", m["description"])

	def test_grabaciones_incluidas(self) -> None:
		carpeta = os.path.join(ADDON, "sonidos", "clock12")
		wavs = sorted(f for f in os.listdir(carpeta) if f.endswith(".wav"))
		self.assertEqual(len(wavs), 48)
		self.assertEqual(wavs[0], "01-00.wav")
		self.assertEqual(wavs[-1], "12-45.wav")
		with wave.open(os.path.join(carpeta, "03-15.wav")) as w:
			self.assertEqual(w.getnchannels(), 1)
			self.assertEqual(w.getsampwidth(), 2)
		# Ya no se repiten en clock24: valen las de 1 a 12.
		self.assertFalse(os.path.isdir(os.path.join(ADDON, "sonidos", "clock24")))

	def test_sin_restos(self) -> None:
		for root, dirs, files in os.walk(ADDON):
			self.assertNotIn("__pycache__", dirs, root)
			for f in files:
				self.assertFalse(f.endswith((".pyc", ".pyo")), f)


class TeclaTests(unittest.TestCase):
	def test_no_choca_con_tiresias(self) -> None:
		"""Tiresias+Control+R es «volver a la configuración guardada»: el reloj usa H."""
		from tiresias.global_commands import GlobalCommands

		self.assertEqual(normalizeGestureId(reloj.LAYER_ENTRY_GESTURE), normalizeGestureId("kb:tiresias+control+h"))
		propias = set()
		for cls in GlobalCommands.__mro__:
			for g in (getattr(cls, "_ScriptableObject__gestures", None) or getattr(cls, "_gestures", None) or {}):
				propias.add(normalizeGestureId(g))
		if not propias:
			import inspect

			from tiresias import global_commands

			src = inspect.getsource(global_commands)
			self.assertIn('gesture="kb:tiresias+control+r"', src)
			self.assertNotIn('"kb:tiresias+control+h"', src)
		else:
			self.assertNotIn(normalizeGestureId("kb:tiresias+control+h"), propias)


class FormatoTests(unittest.TestCase):
	def test_hora_12(self) -> None:
		self.assertEqual(reloj.formatTime(datetime(2026, 11, 18, 15, 45), "12"), "Son las 3:45 de la tarde")
		self.assertEqual(reloj.formatTime(datetime(2026, 11, 18, 1, 0), "12"), "Es la 1 de la noche")
		self.assertEqual(reloj.formatTime(datetime(2026, 11, 18, 9, 5), "12"), "Son las 9:05 de la mañana")

	def test_hora_24(self) -> None:
		self.assertEqual(reloj.formatTime(datetime(2026, 11, 18, 15, 45), "24"), "Son las 15:45")
		self.assertEqual(reloj.formatHourOnTheHour(datetime(2026, 11, 18, 13, 0), "24"), "Son las 13 en punto")

	def test_fecha(self) -> None:
		self.assertEqual(reloj.formatDate(datetime(2026, 11, 18)), "miércoles, 18 de noviembre de 2026")


class GrabacionesTests(unittest.TestCase):
	def setUp(self) -> None:
		self.tmp = tempfile.mkdtemp(prefix="reloj_grab_")
		self.addCleanup(shutil.rmtree, self.tmp, True)
		self.user = os.path.join(self.tmp, "usuario")

	def test_carpeta_de_datos(self) -> None:
		self.assertEqual(os.path.normcase(reloj._userRoot()), os.path.normcase(paths.addonDataDir("RelojTiresias")))

	def test_24_horas_usa_las_de_12(self) -> None:
		ruta = reloj._recordingPath(datetime(2026, 1, 1, 15, 0), "24", self.user, ADDON)
		self.assertEqual(os.path.normcase(ruta), os.path.normcase(os.path.join(ADDON, "sonidos", "clock12", "03-00.wav")))
		ruta = reloj._recordingPath(datetime(2026, 1, 1, 0, 30), "24", self.user, ADDON)
		self.assertTrue(ruta.endswith(os.path.join("clock12", "12-30.wav")))

	def test_las_propias_tienen_preferencia(self) -> None:
		reloj._ensureSoundsFolders(self.user)
		self.assertTrue(os.path.isfile(os.path.join(self.user, "sonidos", "clock24", reloj.SOUNDS_HELP_FILE)))
		propia = os.path.join(self.user, "sonidos", "clock24", "15-00.wav")
		with open(propia, "wb") as f:
			f.write(b"RIFF")
		self.assertEqual(reloj._recordingPath(datetime(2026, 1, 1, 15, 0), "24", self.user, ADDON), propia)
		# En formato de 12 horas sigue la del complemento.
		ruta = reloj._recordingPath(datetime(2026, 1, 1, 15, 0), "12", self.user, ADDON)
		self.assertTrue(ruta.startswith(ADDON))

	def test_sin_grabacion(self) -> None:
		self.assertIsNone(reloj._recordingPath(datetime(2026, 1, 1, 15, 7), "12", self.user, ADDON))


class PluginTests(unittest.TestCase):
	def setUp(self) -> None:
		conf.registerDefaults(reloj.SECTION, reloj.DEFAULTS)
		for k, v in reloj.DEFAULTS.items():
			conf[reloj.SECTION][k] = v
		self.plugin = reloj.GlobalPlugin()
		self.addCleanup(self.plugin.terminate)

	def test_en_espera_no_habla(self) -> None:
		conf[reloj.SECTION]["anunciarCadaHora"] = True
		with mock.patch.object(reloj, "_isStandby", return_value=True), mock.patch.object(self.plugin, "_say") as say, mock.patch.object(self.plugin, "_playRecordingFor") as play, mock.patch.object(
			self.plugin, "_scheduleNextAnnouncement"
		) as again:
			self.plugin._onAnnouncement()
		say.assert_not_called()
		play.assert_not_called()
		again.assert_called_once()

	def test_anuncio_normal(self) -> None:
		conf[reloj.SECTION]["anunciarCadaHora"] = True
		conf[reloj.SECTION]["usarGrabaciones"] = False
		with mock.patch.object(reloj, "_isStandby", return_value=False), mock.patch.object(self.plugin, "_say") as say, mock.patch.object(self.plugin, "_scheduleNextAnnouncement"):
			self.plugin._onAnnouncement()
		say.assert_called_once()

	def test_no_cierra_el_motor_de_tiresias(self) -> None:
		"""Si Tiresias usa ya el motor del reloj (eSpeak...), el reloj no lo cierra."""
		driver = mock.Mock()
		self.plugin._clockSynth = driver
		self.plugin._clockSynthLoadedName = "espeak"
		with mock.patch.object(reloj, "getCurrentSynth", return_value=("espeak", "eSpeak NG")):
			self.plugin._terminateClockSynth()
		driver.terminate.assert_not_called()
		driver.cancel.assert_not_called()
		self.assertIsNone(self.plugin._clockSynth)

	def test_cierra_un_motor_distinto(self) -> None:
		driver = mock.Mock()
		self.plugin._clockSynth = driver
		self.plugin._clockSynthLoadedName = "onecore"
		with mock.patch.object(reloj, "getCurrentSynth", return_value=("eloquence", "Eloquence")):
			self.plugin._terminateClockSynth()
		driver.terminate.assert_called_once()

	def test_suelta_el_motor_si_tiresias_cambia_al_mismo(self) -> None:
		driver = mock.Mock()
		self.plugin._clockSynth = driver
		self.plugin._clockSynthLoadedName = "espeak"
		conf[reloj.SECTION]["motorReloj"] = "espeak"
		with mock.patch.object(reloj, "getCurrentSynth", return_value=("espeak", "eSpeak NG")):
			self.assertIsNone(self.plugin._ensureClockSynth())
		self.assertIsNone(self.plugin._clockSynth)
		driver.terminate.assert_not_called()

	def test_capa(self) -> None:
		self.plugin.script_layerEntry(None)
		self.assertTrue(self.plugin._isLayerActive)
		with mock.patch.object(self.plugin, "_say") as say:
			self.plugin.script_toggleTimeFormat(None)
		say.assert_called_once()
		self.assertFalse(self.plugin._isLayerActive)
		self.assertEqual(conf[reloj.SECTION]["formatoHora"], "24")


if __name__ == "__main__":
	unittest.main()
