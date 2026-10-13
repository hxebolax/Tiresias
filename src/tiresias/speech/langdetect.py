"""Detección automática del idioma de un texto (#2990).

Dos técnicas complementarias, sin dependencias externas:

1. **Guion de escritura Unicode.** Cirílico, griego, árabe, hebreo, chino,
   japonés, coreano, devanagari, tailandés, etc. identifican el idioma (o su
   familia) sin ambigüedad. Se separa el texto en tramos por guion.
2. **Modelo ligero de n-gramas** para el alfabeto latino. Con perfiles de
   trigramas de caracteres de español, inglés, francés, alemán, italiano y
   portugués (calculados al vuelo a partir de textos de muestra propios) se
   elige el idioma más probable. Si el texto es corto o la diferencia entre
   los dos mejores candidatos es pequeña se considera «otros/indeterminado» y
   no se cambia de idioma.
"""

from __future__ import annotations

import math
import re
import threading
import unicodedata
from collections import Counter

# ------------------------------------------------------------------ guiones
#: (inicio, fin, guion)
_SCRIPT_RANGES: list[tuple[int, int, str]] = [
	(0x0041, 0x024F, "latin"),
	(0x1E00, 0x1EFF, "latin"),
	(0x0370, 0x03FF, "greek"),
	(0x1F00, 0x1FFF, "greek"),
	(0x0400, 0x052F, "cyrillic"),
	(0x0530, 0x058F, "armenian"),
	(0x0590, 0x05FF, "hebrew"),
	(0x0600, 0x06FF, "arabic"),
	(0x0750, 0x077F, "arabic"),
	(0x08A0, 0x08FF, "arabic"),
	(0xFB50, 0xFDFF, "arabic"),
	(0xFE70, 0xFEFF, "arabic"),
	(0x0900, 0x097F, "devanagari"),
	(0x0980, 0x09FF, "bengali"),
	(0x0A00, 0x0A7F, "gurmukhi"),
	(0x0A80, 0x0AFF, "gujarati"),
	(0x0B00, 0x0B7F, "oriya"),
	(0x0B80, 0x0BFF, "tamil"),
	(0x0C00, 0x0C7F, "telugu"),
	(0x0C80, 0x0CFF, "kannada"),
	(0x0D00, 0x0D7F, "malayalam"),
	(0x0D80, 0x0DFF, "sinhala"),
	(0x0E00, 0x0E7F, "thai"),
	(0x0E80, 0x0EFF, "lao"),
	(0x0F00, 0x0FFF, "tibetan"),
	(0x1000, 0x109F, "myanmar"),
	(0x10A0, 0x10FF, "georgian"),
	(0x1100, 0x11FF, "hangul"),
	(0x1200, 0x139F, "ethiopic"),
	(0x1780, 0x17FF, "khmer"),
	(0x3040, 0x309F, "hiragana"),
	(0x30A0, 0x30FF, "katakana"),
	(0x31F0, 0x31FF, "katakana"),
	(0x3130, 0x318F, "hangul"),
	(0xAC00, 0xD7AF, "hangul"),
	(0x3400, 0x4DBF, "han"),
	(0x4E00, 0x9FFF, "han"),
	(0xF900, 0xFAFF, "han"),
	(0x20000, 0x2FA1F, "han"),
]

#: Idioma por defecto de cada guion (el latino se resuelve con n-gramas).
SCRIPT_LANGUAGES = {
	"greek": "el",
	"cyrillic": "ru",
	"armenian": "hy",
	"hebrew": "he",
	"arabic": "ar",
	"devanagari": "hi",
	"bengali": "bn",
	"gurmukhi": "pa",
	"gujarati": "gu",
	"oriya": "or",
	"tamil": "ta",
	"telugu": "te",
	"kannada": "kn",
	"malayalam": "ml",
	"sinhala": "si",
	"thai": "th",
	"lao": "lo",
	"tibetan": "bo",
	"myanmar": "my",
	"georgian": "ka",
	"hangul": "ko",
	"ethiopic": "am",
	"khmer": "km",
	"hiragana": "ja",
	"katakana": "ja",
	"han": "zh",
}

_UKRAINIAN = set("іїєґІЇЄҐ")
_PERSIAN = set("پچژگ")


def scriptOf(ch: str) -> str | None:
	"""Guion de un carácter o ``None`` si es neutro (cifras, signos, espacios)."""
	cp = ord(ch)
	if cp < 0x41:
		return None
	if cp < 0x80 and not ch.isalpha():
		return None
	for start, end, name in _SCRIPT_RANGES:
		if start <= cp <= end:
			if name == "latin" and not ch.isalpha():
				return None
			return name
	return None


def splitByScript(text: str) -> list[tuple[str, str | None]]:
	"""Divide ``text`` en tramos ``(texto, guion)``.

	Los caracteres neutros se unen al tramo en curso; los japoneses (kana y
	kanji) se agrupan en un mismo tramo «japanese» si aparece algún kana.
	"""
	runs: list[list] = []
	for ch in text:
		sc = scriptOf(ch)
		if sc in ("hiragana", "katakana"):
			sc = "japanese"
		if not runs:
			runs.append([ch, sc])
			continue
		cur = runs[-1]
		if sc is None or sc == cur[1]:
			cur[0] += ch
		elif cur[1] is None:
			cur[0] += ch
			cur[1] = sc
		elif {sc, cur[1]} == {"han", "japanese"}:
			cur[0] += ch
			cur[1] = "japanese"
		else:
			runs.append([ch, sc])
	# Un tramo final de solo neutros se une al anterior.
	out: list[tuple[str, str | None]] = []
	for t, sc in runs:
		if out and sc is None:
			out[-1] = (out[-1][0] + t, out[-1][1])
		else:
			out.append((t, sc))
	return out


def languageForScript(script: str | None, text: str = "") -> str | None:
	if script in (None, "latin"):
		return None
	if script == "japanese":
		return "ja"
	if script == "cyrillic" and any(c in _UKRAINIAN for c in text):
		return "uk"
	if script == "arabic" and any(c in _PERSIAN for c in text):
		return "fa"
	return SCRIPT_LANGUAGES.get(script)


# ------------------------------------------------------------------ n-gramas
# Textos de muestra escritos para Tiresias (no proceden de ningún corpus).
_SAMPLES = {
	"es": (
		"El lector de pantalla lee en voz alta todo lo que aparece en el ordenador. "
		"Cuando abres una carpeta, te dice cuántos archivos hay y cómo se llaman. "
		"Si escribes una carta, puedes repasar cada palabra y corregir los errores sin ayuda. "
		"Mañana por la mañana iremos al mercado para comprar fruta, pan y queso del pueblo. "
		"La reunión de vecinos se celebró ayer en el salón de actos y duró casi dos horas. "
		"Los niños jugaban en el parque mientras sus padres hablaban de las vacaciones de verano. "
		"Es importante que la información sea clara, que esté bien ordenada y que no haya prisas. "
		"Hemos recibido su solicitud y le responderemos en un plazo de quince días hábiles. "
		"¿Quieres que te acompañe a la estación o prefieres ir tú solo en el autobús de las ocho? "
		"Para guardar los cambios pulse el botón aceptar; para descartarlos, pulse cancelar. "
		"Según el informe, las ventas de este año han crecido más de lo que se esperaba. "
		"La ciudad tiene calles estrechas, plazas antiguas y muchos bares con terraza junto al río."
	),
	"en": (
		"The screen reader speaks aloud everything that appears on the computer. "
		"When you open a folder, it tells you how many files there are and what they are called. "
		"If you write a letter, you can review each word and fix the mistakes without any help. "
		"Tomorrow morning we will go to the market to buy some fruit, bread and cheese from the farm. "
		"The neighbours met yesterday in the town hall and the meeting lasted almost two hours. "
		"The children were playing in the park while their parents talked about the summer holidays. "
		"It is important that the information is clear, well organised and that nobody is rushed. "
		"We have received your request and we will reply within fifteen working days. "
		"Would you like me to walk with you to the station, or would you rather take the bus at eight? "
		"To save your changes press the OK button; to discard them, press cancel. "
		"According to the report, sales this year have grown more than anyone expected. "
		"The city has narrow streets, old squares and plenty of cafes with tables next to the river. "
		"This is what they should have thought about before they went through with it."
	),
	"fr": (
		"Le lecteur d'écran lit à voix haute tout ce qui apparaît sur l'ordinateur. "
		"Quand vous ouvrez un dossier, il vous dit combien de fichiers il contient et comment ils s'appellent. "
		"Si vous écrivez une lettre, vous pouvez relire chaque mot et corriger les fautes sans aide. "
		"Demain matin nous irons au marché pour acheter des fruits, du pain et du fromage de la ferme. "
		"Les voisins se sont réunis hier à la mairie et la réunion a duré presque deux heures. "
		"Les enfants jouaient dans le parc pendant que leurs parents parlaient des vacances d'été. "
		"Il est important que l'information soit claire, bien rangée et que personne ne soit pressé. "
		"Nous avons bien reçu votre demande et nous vous répondrons dans un délai de quinze jours ouvrés. "
		"Veux-tu que je t'accompagne à la gare ou préfères-tu prendre le bus de huit heures ? "
		"Pour enregistrer vos modifications, appuyez sur le bouton valider ; pour les annuler, appuyez sur annuler."
	),
	"de": (
		"Der Bildschirmleser liest alles laut vor, was auf dem Computer erscheint. "
		"Wenn du einen Ordner öffnest, sagt er dir, wie viele Dateien darin sind und wie sie heißen. "
		"Wenn du einen Brief schreibst, kannst du jedes Wort prüfen und die Fehler ohne Hilfe korrigieren. "
		"Morgen früh gehen wir auf den Markt, um Obst, Brot und Käse vom Bauernhof zu kaufen. "
		"Die Nachbarn haben sich gestern im Rathaus getroffen und die Sitzung dauerte fast zwei Stunden. "
		"Die Kinder spielten im Park, während ihre Eltern über die Sommerferien sprachen. "
		"Es ist wichtig, dass die Informationen klar und gut geordnet sind und dass niemand hetzen muss. "
		"Wir haben Ihre Anfrage erhalten und werden Ihnen innerhalb von fünfzehn Werktagen antworten. "
		"Soll ich dich zum Bahnhof begleiten, oder möchtest du lieber den Bus um acht Uhr nehmen? "
		"Um die Änderungen zu speichern, drücken Sie die Schaltfläche OK; zum Verwerfen drücken Sie Abbrechen."
	),
	"it": (
		"Il lettore di schermo legge ad alta voce tutto quello che appare sul computer. "
		"Quando apri una cartella, ti dice quanti file ci sono e come si chiamano. "
		"Se scrivi una lettera, puoi rileggere ogni parola e correggere gli errori senza aiuto. "
		"Domani mattina andremo al mercato per comprare frutta, pane e formaggio della fattoria. "
		"I vicini si sono riuniti ieri in municipio e la riunione è durata quasi due ore. "
		"I bambini giocavano nel parco mentre i loro genitori parlavano delle vacanze estive. "
		"È importante che le informazioni siano chiare, ben ordinate e che nessuno abbia fretta. "
		"Abbiamo ricevuto la sua richiesta e le risponderemo entro quindici giorni lavorativi. "
		"Vuoi che ti accompagni alla stazione o preferisci prendere l'autobus delle otto? "
		"Per salvare le modifiche premi il pulsante conferma; per annullarle, premi annulla."
	),
	"pt": (
		"O leitor de ecrã lê em voz alta tudo o que aparece no computador. "
		"Quando abres uma pasta, ele diz-te quantos ficheiros existem e como se chamam. "
		"Se escreveres uma carta, podes rever cada palavra e corrigir os erros sem ajuda. "
		"Amanhã de manhã vamos ao mercado comprar fruta, pão e queijo da quinta. "
		"Os vizinhos reuniram-se ontem na câmara municipal e a reunião durou quase duas horas. "
		"As crianças brincavam no parque enquanto os pais falavam sobre as férias de verão. "
		"É importante que a informação seja clara, bem organizada e que ninguém tenha pressa. "
		"Recebemos o seu pedido e vamos responder no prazo de quinze dias úteis. "
		"Queres que te acompanhe à estação ou preferes apanhar o autocarro das oito? "
		"Não há nada que não possamos resolver juntos, são coisas que acontecem."
	),
}

#: Idiomas que el modelo distingue.
MODEL_LANGUAGES = tuple(_SAMPLES)

_nonLetters = re.compile(r"[^\w']+|[\d_]+")
_ALPHA = 0.5


def _normalize(text: str) -> str:
	return " " + " ".join(_nonLetters.sub(" ", text.lower()).split()) + " "


def _trigrams(text: str) -> list[str]:
	t = _normalize(text)
	return [t[i : i + 3] for i in range(len(t) - 2)]


class NgramModel:
	def __init__(self, samples: dict[str, str]) -> None:
		self.counts: dict[str, Counter] = {}
		self.totals: dict[str, int] = {}
		vocab: set[str] = set()
		for lang, text in samples.items():
			c = Counter(_trigrams(text))
			self.counts[lang] = c
			self.totals[lang] = sum(c.values())
			vocab.update(c)
		self.vocabSize = len(vocab) + 1

	def scores(self, text: str) -> dict[str, float]:
		"""Log-probabilidad media por trigrama de cada idioma."""
		grams = _trigrams(text)
		if not grams:
			return {}
		out: dict[str, float] = {}
		for lang, c in self.counts.items():
			denom = self.totals[lang] + _ALPHA * self.vocabSize
			s = 0.0
			for g in grams:
				s += math.log((c.get(g, 0) + _ALPHA) / denom)
			out[lang] = s / len(grams)
		return out


_model: NgramModel | None = None
_modelLock = threading.Lock()


def getModel() -> NgramModel:
	global _model
	if _model is None:
		with _modelLock:
			if _model is None:
				_model = NgramModel(_SAMPLES)
	return _model


#: Mínimo de letras para fiarse del modelo de n-gramas.
MIN_LETTERS = 20
#: Diferencia mínima (por trigrama) entre el primer y el segundo candidato.
MIN_MARGIN = 0.12


def detectLatin(text: str, preferred: str | None = None) -> tuple[str | None, float]:
	"""Idioma de un texto en alfabeto latino: ``(idioma, margen)``.

	``idioma`` es ``None`` si el texto es demasiado corto o ambiguo. Se da
	ventaja a ``preferred`` (normalmente el idioma de la voz) para no cambiar
	de idioma sin motivo.
	"""
	letters = sum(1 for ch in text if ch.isalpha())
	if letters < MIN_LETTERS:
		return None, 0.0
	scores = getModel().scores(text)
	if not scores:
		return None, 0.0
	base = (preferred or "").split("_")[0].lower()
	if base in scores:
		scores[base] += MIN_MARGIN / 2
	ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
	best, bestScore = ranked[0]
	margin = bestScore - ranked[1][1] if len(ranked) > 1 else 1.0
	if margin < MIN_MARGIN:
		return None, margin
	return best, margin


def detectSegments(text: str, voiceLanguage: str | None, useNgrams: bool = True) -> list[tuple[str, str | None]]:
	"""Divide ``text`` en tramos ``(texto, idioma)``.

	``idioma`` es ``None`` cuando el tramo debe leerse con el idioma de la
	voz. Los tramos latinos largos se analizan por frases con el modelo de
	n-gramas si ``useNgrams`` es ``True``.
	"""
	voiceBase = (voiceLanguage or "").split("_")[0].lower()
	out: list[tuple[str, str | None]] = []

	def add(t: str, lang: str | None) -> None:
		if lang and lang.split("_")[0] == voiceBase:
			lang = None
		if out and out[-1][1] == lang:
			out[-1] = (out[-1][0] + t, lang)
		else:
			out.append((t, lang))

	for chunk, script in splitByScript(text):
		if script == "latin" and useNgrams:
			for sentence in _splitSentences(chunk):
				lang, _m = detectLatin(sentence, voiceLanguage)
				add(sentence, lang)
		else:
			lang = languageForScript(script, chunk)
			# Una letra suelta (por ejemplo «α» en una fórmula) no cambia de idioma.
			needed = 1 if script in ("han", "japanese", "hangul") else MIN_SCRIPT_LETTERS
			if lang and sum(1 for ch in chunk if scriptOf(ch) not in (None, "latin")) < needed:
				lang = None
			add(chunk, lang)
	return out


#: Letras mínimas de un guion no latino para cambiar de idioma.
MIN_SCRIPT_LETTERS = 3


_sentenceRe = re.compile(r".+?(?:[.!?…]+[\"'»”)\]]*(?:\s+|$)|\n+|$)", re.S)


def _splitSentences(text: str) -> list[str]:
	parts = [m.group(0) for m in _sentenceRe.finditer(text) if m.group(0)]
	return parts or [text]


def isMostlyLetters(text: str) -> bool:
	letters = sum(1 for ch in text if unicodedata.category(ch).startswith("L"))
	return letters >= max(1, len(text.strip()) // 3)
