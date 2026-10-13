"""Conversión de texto a fonemas IPA con eSpeak NG (para las voces Piper).

Las voces Piper se entrenaron con los fonemas IPA que produce eSpeak NG, así
que se usa la misma biblioteca que el sintetizador eSpeak de Tiresias
(``espeak-ng.dll`` y ``espeak-ng-data``), pero cargada desde una **copia
privada** de la DLL (``data/cache/piper/espeak-ng-piper.dll``): eSpeak NG
guarda estado global y así el controlador eSpeak y el de Piper no se pisan
(cada uno puede inicializar, cambiar de voz o terminar su copia).
"""

from __future__ import annotations

import ctypes
import os
import re
import shutil
import threading
import unicodedata
from ctypes import c_char_p, c_int, c_void_p

from .. import paths
from ..log import getLogger

log = getLogger("piperPhonemizer")

AUDIO_OUTPUT_SYNCHRONOUS = 2
espeakCHARS_UTF8 = 1
espeakPHONEMES_IPA = 0x02
EE_OK = 0

#: Signos de puntuación que se conservan como fonemas (Piper los usa para la entonación y las pausas).
PUNCTUATION = ".,;:!?¡¿…"
# Los puntos, comas y dos puntos entre cifras («1.500», «3,14», «12:30») no
# separan cláusulas: si se cortaba ahí, eSpeak leía «uno. quinientos».
_splitPunct = re.compile(r"((?:[;!?¡¿…]|(?<!\d)[.,:]|[.,:](?!\d))+)")
_sentenceEnd = re.compile(r"(?<=[.!?…])\s+")


class espeak_VOICE(ctypes.Structure):
	_fields_ = [
		("name", c_char_p),
		("languages", c_char_p),
		("identifier", c_char_p),
		("gender", ctypes.c_ubyte),
		("age", ctypes.c_ubyte),
		("variant", ctypes.c_ubyte),
		("xx1", ctypes.c_ubyte),
		("score", c_int),
		("spare", c_void_p),
	]


def _privateDllCopy(dllPath: str) -> str:
	"""Copia la DLL de eSpeak NG con otro nombre para tener una instancia propia."""
	folder = os.path.join(paths.cacheDir(), "piper")
	dest = os.path.join(folder, "espeak-ng-piper.dll")
	try:
		os.makedirs(folder, exist_ok=True)
		if not os.path.isfile(dest) or os.path.getsize(dest) != os.path.getsize(dllPath) or os.path.getmtime(dest) < os.path.getmtime(dllPath):
			shutil.copy2(dllPath, dest)
		return dest
	except OSError:
		log.warning("No se pudo copiar la DLL de eSpeak NG; se comparte con el sintetizador eSpeak", exc_info=True)
		return dllPath


class Phonemizer:
	"""Texto -> cadenas de fonemas IPA, con la voz de eSpeak NG indicada."""

	def __init__(self) -> None:
		from .espeak import findLibrary

		found = findLibrary()
		if not found:
			raise RuntimeError("No se encontró eSpeak NG (necesario para las voces Piper)")
		dllPath, dataParent = found
		os.add_dll_directory(os.path.dirname(dllPath))
		self._dll = ctypes.CDLL(_privateDllCopy(dllPath))
		d = self._dll
		d.espeak_Initialize.argtypes = [c_int, c_int, c_char_p, c_int]
		d.espeak_Initialize.restype = c_int
		d.espeak_SetVoiceByName.argtypes = [c_char_p]
		d.espeak_SetVoiceByName.restype = c_int
		d.espeak_SetVoiceByProperties.argtypes = [ctypes.POINTER(espeak_VOICE)]
		d.espeak_SetVoiceByProperties.restype = c_int
		d.espeak_TextToPhonemes.argtypes = [ctypes.POINTER(c_void_p), c_int, c_int]
		d.espeak_TextToPhonemes.restype = c_char_p
		if d.espeak_Initialize(AUDIO_OUTPUT_SYNCHRONOUS, 0, dataParent.encode("mbcs"), 0) <= 0:
			raise RuntimeError("eSpeak NG no pudo inicializarse para Piper")
		self._voice: str | None = None
		self._lock = threading.Lock()

	def setVoice(self, voice: str) -> None:
		if voice == self._voice:
			return
		if self._dll.espeak_SetVoiceByName(voice.encode("utf-8")) != EE_OK:
			props = espeak_VOICE()
			props.languages = voice.encode("utf-8")
			if self._dll.espeak_SetVoiceByProperties(ctypes.byref(props)) != EE_OK:
				raise ValueError(f"eSpeak NG no tiene la voz {voice}")
		self._voice = voice

	def _clauseToIpa(self, text: str) -> str:
		# Sin NUL (cortaría el texto) y sin surrogates sueltos (no se pueden codificar).
		text = text.replace("\x00", " ")
		buf = ctypes.create_string_buffer(text.encode("utf-8", "replace"))
		ptr = c_void_p(ctypes.addressof(buf))
		parts: list[str] = []
		while ptr.value:
			res = self._dll.espeak_TextToPhonemes(ctypes.byref(ptr), espeakCHARS_UTF8, espeakPHONEMES_IPA)
			if res:
				parts.append(res.decode("utf-8", "replace").strip())
		return " ".join(p for p in parts if p)

	def phonemize(self, text: str, voice: str) -> list[str]:
		"""Fonemas IPA de ``text``: una cadena por frase, con la puntuación conservada."""
		with self._lock:
			self.setVoice(voice)
			sentences: list[str] = []
			for sentence in _sentenceEnd.split(text):
				if not sentence.strip():
					continue
				out = ""
				for piece in _splitPunct.split(sentence):
					if not piece:
						continue
					if _splitPunct.fullmatch(piece):
						# Signos de apertura del español: no se pronuncian.
						marks = "".join(c for c in piece if c not in "¡¿")
						if marks:
							out = out.rstrip() + marks[:1].replace("…", ".") + " "
						continue
					ipa = self._clauseToIpa(piece.strip()) if piece.strip() else ""
					if ipa:
						out += ipa + " "
				out = out.strip()
				if out:
					sentences.append(out)
			return sentences


def phonemesToIds(phonemes: str, idMap: dict[str, list[int]]) -> list[int]:
	"""Identificadores para el modelo: ``^``, cada fonema seguido de ``_`` y ``$``."""
	pad = idMap.get("_", [0])
	ids: list[int] = list(idMap.get("^", [1])) + list(pad)
	for ch in unicodedata.normalize("NFD", phonemes):
		mapped = idMap.get(ch)
		if mapped is None:
			continue
		ids.extend(mapped)
		ids.extend(pad)
	ids.extend(idMap.get("$", [2]))
	return ids
