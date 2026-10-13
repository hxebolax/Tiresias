"""Pruebas de regresión de la versión 1.0.10: eSpeak NG y el español de Latinoamérica.

- La voz «es-419» se mantiene en todas las frases (la etiqueta raíz <speak>
  hacía que eSpeak volviera a la voz de España después de la primera).
- Al volver de un cambio de idioma se usa otra vez la voz elegida.
- Se reconocen los identificadores de voz de NVDA («roa\\es-419», «en»).
- El importador de NVDA entiende la barra de Windows en la voz de eSpeak.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_rev1010 -v``
"""

from __future__ import annotations

import ctypes
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import nvda_import  # noqa: E402
from tiresias.speech.commands import (  # noqa: E402
	BreakCommand,
	CharacterModeCommand,
	LangChangeCommand,
	RateCommand,
)
from tiresias.synth import espeak  # noqa: E402

BACKSLASH = chr(92)


class ImportadorTests(unittest.TestCase):
	def test_voz_con_barra_de_windows(self) -> None:
		self.assertEqual(nvda_import._espeakVoice("roa" + BACKSLASH + "es-419"), "es-419")
		self.assertEqual(nvda_import._espeakVoice("roa/pt-BR"), "pt-br")
		self.assertEqual(nvda_import._espeakVoice("es-419"), "es-419")


@unittest.skipUnless(espeak.SynthDriver.check(), "eSpeak NG no está disponible")
class ESpeakLatinoamericaTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		cls.d = espeak.SynthDriver()
		cls.d._dll.espeak_GetCurrentVoice.restype = ctypes.POINTER(espeak.espeak_VOICE)

	def say(self, items: list) -> list[bytes]:
		chunks: list[bytes] = []
		self.d._synthesizeSegment(items, chunks.append, lambda: False)
		return chunks

	def currentVoice(self) -> str:
		return self.d._dll.espeak_GetCurrentVoice().contents.identifier.decode().replace(BACKSLASH, "/")

	def test_resolver_identificadores_de_nvda(self) -> None:
		d = self.d
		self.assertEqual(d._resolveVoice("es-419"), "es-419")
		self.assertEqual(d._resolveVoice("roa" + BACKSLASH + "es-419"), "es-419")
		self.assertEqual(d._resolveVoice("ROA/ES-419"), "es-419")
		self.assertEqual(d._resolveVoice("en"), "en-gb")
		self.assertIsNone(d._resolveVoice("no-existe"))

	def test_todas_las_voces_se_pueden_elegir(self) -> None:
		d = self.d
		for voiceId, ident in d._identifiers.items():
			self.assertEqual(d._dll.espeak_SetVoiceByName(ident.encode()), espeak.EE_OK, voiceId)

	def test_es419_se_mantiene_frase_tras_frase(self) -> None:
		self.d.loadSettings({"voice": "roa" + BACKSLASH + "es-419", "variant": "max"})
		self.assertEqual(self.d._settings["voice"], "es-419")
		self.assertEqual(self.d.language, "es-419")
		for _i in range(3):
			self.assertTrue(self.say(["cielo zapato"]))
			self.assertEqual(self.currentVoice(), "roa/es-419+max")

	def test_vuelve_a_es419_tras_cambiar_de_idioma(self) -> None:
		self.d.loadSettings({"voice": "es-419", "variant": ""})
		runs = self.d._buildRuns([RateCommand(offset=30), "cielo ", LangChangeCommand("en_US"), "hello ", LangChangeCommand(None), "cerveza", CharacterModeCommand(True), "ab", CharacterModeCommand(False), BreakCommand(100)])
		self.assertEqual([lang for lang, _s in runs], [None, "en-us", None])
		# La prosodia abierta se repite en cada tramo y todos quedan cerrados.
		for _lang, ssml in runs:
			self.assertTrue(ssml.startswith('<prosody rate="130%">'), ssml)
			self.assertEqual(ssml.count("<prosody"), ssml.count("</prosody>"))
			self.assertNotIn("<speak", ssml)
			self.assertNotIn("<voice", ssml)
		self.say([LangChangeCommand("en"), "hello", LangChangeCommand(None), "cielo"])
		self.assertEqual(self.currentVoice(), "roa/es-419")
		self.say(["cielo"])
		self.assertEqual(self.currentVoice(), "roa/es-419")

	def test_espana_sigue_igual(self) -> None:
		self.d.loadSettings({"voice": "es", "variant": ""})
		self.say([LangChangeCommand("en"), "hello", LangChangeCommand(None), "cielo"])
		self.assertEqual(self.currentVoice(), "roa/es")


if __name__ == "__main__":
	unittest.main()
