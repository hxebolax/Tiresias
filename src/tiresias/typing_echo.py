"""Eco de teclado: caracteres y palabras escritos."""

from __future__ import annotations

import collections
import re
import time
import unicodedata

from . import speech
from .config import conf
from .log import getLogger

log = getLogger("typingEcho")

_word: list[str] = []
_recent: collections.deque[tuple[float, str]] = collections.deque(maxlen=200)
#: La palabra en curso empezó justo después de un separador escrito por el
#: usuario (no se está editando una palabra que ya existía).
_wordClean = True

# El apóstrofo no separa palabras («don't», «l'aigua») (#13565).
_WORD_SEPARATORS = set(" \t\n\r.,;:!?¿¡()[]{}\"«»/\\|-—–")
_trailingWord = re.compile(r"[\w'’]+$")


def _modeActive(setting: str, obj) -> bool:
	mode = conf["keyboard"][setting]
	if mode in (False, "off"):
		return False
	if mode in (True, "always"):
		return True
	if mode == "editOnly":
		try:
			return bool(obj and obj.isEditable)
		except Exception:
			return False
	return False


def recentlyTyped(text: str) -> bool:
	"""``True`` si ``text`` coincide con lo escrito en los últimos segundos."""
	now = time.monotonic()
	typed = "".join(ch for t, ch in _recent if now - t < 3)
	text = text.strip()
	return bool(text) and typed.strip().endswith(text[-min(len(text), 20):]) if typed else False


def onTypedCharacter(obj, ch: str) -> None:
	global _wordClean
	if ch and len(ch) > 1:
		# Una tecla puede producir varios caracteres (acento que no se combina,
		# AltGr, IME...): se tratan uno a uno.
		for c in ch:
			onTypedCharacter(obj, c)
		return
	from .privacy import isProtected

	# Campo de contraseña (rol o estado «protegido»; si no se puede saber, también):
	# solo un asterisco y nada se guarda en lo escrito recientemente.
	if isProtected(obj):
		if ch and not (unicodedata.category(ch)[0] == "C" and ch not in "\r\n\t") and _modeActive("speakTypedCharacters", obj):
			with speech.speechOrigin(speech.ORIGIN_TYPING):
				speech.speak(speech.contextSequence("typing", ["*"]))
		return
	prev = _recent[-1] if _recent else None
	_recent.append((time.monotonic(), ch))
	if not ch or unicodedata.category(ch)[0] == "C" and ch not in "\r\n\t":
		return
	speakChars = _modeActive("speakTypedCharacters", obj)
	speakWords = _modeActive("speakTypedWords", obj)
	if ch.isprintable():
		checkFormatAfterTyping(obj)
	if ch in _WORD_SEPARATORS or ch in "\r\n":
		word = "".join(_word).strip()
		_word.clear()
		if word and conf["keyboard"]["alertForSpellingErrors"]:
			_scheduleSpellingCheck(obj)
		clean = _wordClean
		_wordClean = True
		if speakWords and word:
			if speakChars and ch.isprintable():
				speech.speakTypedCharacter(ch)
			if not clean and conf["keyboard"]["speakWholeEditedWord"] and obj is not None and getattr(obj, "hasText", False):
				# Se ha editado una palabra existente: se lee la palabra completa
				# del texto (cuando la aplicación ya la tenga) y no solo lo
				# escrito (#8065).
				from . import queue_handler

				queue_handler.callLater(60, _speakEditedWord, obj, word)
				return
			speech.speakTypedWord(word)
			return
		if not ch.isprintable():
			# Intro y tabulador solo cierran la palabra: no se anuncian.
			return
	elif ch == "\b":
		if _word:
			_word.pop()
		else:
			_wordClean = False
		return
	else:
		if not _word:
			# La palabra es «limpia» si lo anterior fue un separador escrito hace poco.
			_wordClean = bool(prev) and time.monotonic() - prev[0] < 30 and (prev[1] in _WORD_SEPARATORS or prev[1] in "\r\n")
		_word.append(ch)
	if speakChars:
		if conf["keyboard"]["speechInterruptForCharacters"]:
			speech.cancelSpeech()
		speech.speakTypedCharacter(ch)


def resetWord() -> None:
	global _wordClean
	_word.clear()
	_wordClean = False


def wordBeforeCaret(textBefore: str) -> str:
	"""Última palabra de ``textBefore`` sin los separadores finales."""
	stripped = textBefore.rstrip("".join(_WORD_SEPARATORS))
	m = _trailingWord.search(stripped)
	return m.group(0) if m else ""


def _speakEditedWord(obj, typed: str) -> None:
	from . import textinfo

	word = ""
	try:
		caret = obj.makeTextInfo(textinfo.POSITION_CARET)
		line = caret.copy()
		line.expand(textinfo.UNIT_LINE)
		before = line.copy()
		before.setEndPoint(caret, "endToStart")
		word = wordBeforeCaret(before.text)
	except Exception:
		log.debug("No se pudo leer la palabra editada", exc_info=True)
	# Si el texto no contiene lo escrito (la aplicación aún no lo ha
	# actualizado o no expone su texto), se dice lo escrito.
	if not word or typed.lower() not in word.lower():
		word = typed
	speech.speakTypedWord(word)


def _scheduleSpellingCheck(obj) -> None:
	"""Comprueba (poco después) si la palabra recién escrita tiene error ortográfico."""
	from . import queue_handler

	if obj is None or not getattr(obj, "hasText", False):
		return
	queue_handler.callLater(120, _checkPreviousWord, obj)


def _checkPreviousWord(obj) -> None:
	from . import textinfo
	from .audio import tones

	try:
		info = obj.makeTextInfo(textinfo.POSITION_CARET)
		word = info.copy()
		word.move(textinfo.UNIT_WORD, -1)
		word.expand(textinfo.UNIT_WORD)
		check = getattr(word, "hasSpellingError", None)
		if check is not None and check():
			tones.playSound("textError")
	except Exception:
		log.debug("No se pudo comprobar la ortografía", exc_info=True)


def checkFormatAfterTyping(obj) -> None:
	"""«Detectar cambios de formato tras el cursor»: al escribir se anuncian."""
	if obj is None or not getattr(obj, "hasText", False):
		return
	if not conf["documentFormatting"]["detectFormatAfterCursor"]:
		return
	from . import queue_handler

	queue_handler.callLater(80, _speakFormatAtCaret, obj)


def _speakFormatAtCaret(obj) -> None:
	from . import formatting, textinfo

	try:
		info = obj.makeTextInfo(textinfo.POSITION_CARET)
		parts = formatting.speechForMove(info)
	except Exception:
		return
	if parts:
		speech.speakText(" ".join(parts))
