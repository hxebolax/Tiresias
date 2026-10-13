"""Paneles de opciones del núcleo de voz y lectura.

- **Lectura de texto**: números, lectura alfanumérica, entidades HTML y
  lectura continua (con la lectura rápida).
- **Idioma de la voz**: detección automática, anuncio del idioma e idioma
  no admitido.
- **Voces y esquemas**: voces por contexto (cursor, revisión, eco de teclado,
  mensajes, menús y diálogos: voz, puntuación, velocidad, tono y volumen) y
  esquema de voz y sonido (también fuera del modo exploración).
- **Verbosidad**: nivel, mensajes de tutor y orden de las propiedades.

Las tres primeras van detrás de «Voz» y «Verbosidad», detrás de
«Presentación de objetos» (ver ``settings.PANEL_ORDER``).
"""

from __future__ import annotations

from typing import Any

import wx

from ..config import conf
from ..i18n import _
from . import settings as S

_NUMBERS = [
	("full", _("Números completos")),
	("digits", _("Dígito a dígito")),
	("pairs", _("Por pares de cifras")),
	("triples", _("Por grupos de tres cifras")),
]
_SAYALL_UNITS = [("line", _("Por líneas")), ("sentence", _("Por frases")), ("paragraph", _("Por párrafos"))]
#: Qué cambian Re Pág y Av Pág durante la lectura continua (foros 2.1).
_SAYALL_RATE_MODES = [
	("sayAll", _("La velocidad propia de la lectura continua (se recuerda)")),
	("temporary", _("Solo la lectura en curso (al acabar vuelve a la normal)")),
	("global", _("La velocidad de la voz (para todo)")),
]
_CAPITALS = [
	("off", _("No indicar")),
	("initial", _("Palabras que empiezan por mayúscula")),
	("allCaps", _("Solo palabras enteras en mayúsculas")),
]
_DETECTION = [
	("off", _("Desactivada")),
	("script", _("Por alfabeto (cirílico, griego, árabe, chino...)")),
	("full", _("Por alfabeto y por palabras (distingue español, inglés y otros)")),
]
_NOT_SUPPORTED = [("speech", _("Decirlo con voz")), ("beep", _("Pitido")), ("off", _("No avisar"))]
_TUTOR = [("off", _("Desactivados")), ("complex", _("Solo en controles complejos")), ("all", _("En todos los controles"))]


class SpeechReadingPanel(S.ConfigPanel):
	title = _("Lectura de texto")
	section = "speech"

	def getFields(self) -> list[S.Field]:
		gt = _("Números y texto")
		gs = _("Lectura continua")
		# Los modos de voz están en «Voz»; el eco de palabras, en «Teclado»; las teclas
		# de acceso, en «Presentación de objetos».
		return [
			S.Choice("numberReading", _("Lectura de números:"), _NUMBERS, group=gt),
			S.Bool("splitAlphanumeric", _("Lectura alfanumérica: separar letras y números («abc123»)"), group=gt),
			S.Bool("decodeHtmlEntities", _("Leer las entidades HTML (por ejemplo «&&amp;») como su carácter"), group=gt),
			S.Choice("sayAllUnit", _("Leer todo:"), _SAYALL_UNITS, group=gs),
			S.Bool("sayAllWithoutPauses", _("Leer todo sin pausas en los saltos de línea"), group=gs),
			S.Int("sayAllRateOffset", _("Velocidad propia de la lectura continua (puntos sobre la de la voz; 0 = igual):"), -100, 100, group=gs),
			S.Choice("capitalsInSayAll", _("Indicar las mayúsculas al leer todo:"), _CAPITALS, group=gs),
			S.Bool("allowSkimReadingInSayAll", _("Permitir la lectura rápida durante la lectura continua"), section="keyboard", group=gs),
			S.Bool("sayAllNavigationKeys", _("Durante la lectura continua, Re Pág y Av Pág cambian la velocidad y las flechas saltan frases y párrafos"), group=gs),
			S.Choice("sayAllRateMode", _("Re Pág y Av Pág durante la lectura continua cambian:"), _SAYALL_RATE_MODES, group=gs),
			S.Int("sayAllRateStep", _("Cambio de velocidad con Re Pág y Av Pág:"), 1, 50, group=gs),
		]


class SpeechLanguagePanel(S.ConfigPanel):
	title = _("Idioma de la voz")
	section = "speech"

	def getFields(self) -> list[S.Field]:
		return [
			S.Bool("autoLanguageSwitching", _("Cambio automático de idioma (si la voz lo admite)")),
			S.Bool("autoDialectSwitching", _("Cambio automático de dialecto (si la voz lo admite)")),
			S.Choice("languageDetection", _("Detección automática del idioma del texto:"), _DETECTION),
			S.Bool("reportLanguage", _("Anunciar el idioma al cambiar de idioma")),
			S.Choice("reportNotSupportedLanguage", _("Si la voz no admite el idioma:"), _NOT_SUPPORTED),
			S.Bool("trustVoiceLanguage", _("Usar la tabla de símbolos y las descripciones del idioma de la voz")),
		]

	def makeExtraSettings(self, builder: S.SettingsBuilder) -> None:
		builder.addStaticText(
			_("Los mensajes de Tiresias se dicen siempre en el idioma de la interfaz, aunque la voz hable otro idioma, si el cambio automático de idioma está activado.")
		)


class VoiceContextsPanel(S.ConfigPanel):
	title = _("Voces y esquemas")
	section = "speech"

	def getFields(self) -> list[S.Field]:
		from ..speech import voice_schemes as vs

		# La velocidad propia del eco de teclado, que vale siempre, está en «Teclado».
		fields: list[S.Field] = [
			S.Bool("voiceContexts", _("Usar voces distintas según el contexto"), group=_("Voces por contexto")),
		]
		for ctx in vs.CONTEXTS:
			g = vs.CONTEXT_LABELS[ctx]
			# Otra voz del mismo sintetizador y otro nivel de puntuación (foros 2.3).
			# Las voces del sintetizador se leen en el núcleo (ver _onVoiceChoices).
			fields.append(S.Choice(vs.contextKey(ctx, "Voice"), _("Voz:"), _cachedVoiceChoices, group=g))
			fields.append(S.Choice(vs.contextKey(ctx, "SymbolLevel"), _("Nivel de puntuación:"), vs.contextSymbolLevelChoices, group=g))
			if ctx != "typing":
				fields.append(S.Int(vs.contextKey(ctx, "Rate"), _("Velocidad (cambio en porcentaje):"), -80, 200, group=g))
			fields.append(S.Int(vs.contextKey(ctx, "Pitch"), _("Tono (cambio en porcentaje):"), -80, 80, group=g))
			fields.append(S.Int(vs.contextKey(ctx, "Volume"), _("Volumen (cambio en porcentaje):"), -90, 0, group=g))
		gs = _("Esquema de voz y sonido")
		fields.append(S.Choice("voiceScheme", _("Esquema de voz y sonido:"), vs.schemeChoices, group=gs))
		# foros 2.4: también en los controles con el foco y en el texto editable.
		fields.append(S.Bool("voiceSchemeEverywhere", _("Aplicar el esquema también fuera del modo exploración (controles y texto editable)"), group=gs))
		return fields

	def makeExtraSettings(self, builder: S.SettingsBuilder) -> None:
		btn = builder.addButton(_("&Editar los esquemas de voz y sonido..."))
		btn.Bind(wx.EVT_BUTTON, lambda evt: _openSpeechDialog("showVoiceSchemes", self._refreshSchemes))
		from ..speech import voice_schemes as vs

		# availableVoices pertenece al sintetizador: se consulta en el núcleo.
		S.runOnCore(vs.contextVoiceChoices, callback=self._onVoiceChoices)

	def _onVoiceChoices(self, choices: list[tuple[str, str]] | None) -> None:
		global _voiceChoicesCache
		if not choices or not S.isAlive(self):
			return
		from ..speech import voice_schemes as vs

		_voiceChoicesCache = list(choices)
		for ctx in vs.CONTEXTS:
			self.updateChoices(vs.contextKey(ctx, "Voice"), choices)

	def _refreshSchemes(self) -> None:
		"""Vuelve a leer los esquemas tras editarlos con el botón."""
		if not S.isAlive(self):
			return
		from ..speech import voice_schemes as vs

		b = self._bound.get(("speech", "voiceScheme"))
		if b is None:
			return
		saved = conf["speech"]["voiceScheme"]
		# Si el diálogo cambió el nombre del esquema elegido (o lo borró) y aquí
		# no se había tocado, la lista pasa a mostrar el valor nuevo.
		follow = self.getValue("voiceScheme") == b.original and saved != b.original
		if follow:
			b.original = saved
		choices = vs.schemeChoices()
		self.updateChoices("voiceScheme", choices)
		if follow:
			self.setControlValue("voiceScheme", saved)
			self.updateChoices("voiceScheme", choices)


class VerbosityPanel(S.ConfigPanel):
	title = _("Verbosidad")
	section = "presentation"

	def getFields(self) -> list[S.Field]:
		from ..speech import verbosity

		return [
			S.Choice("verbosity", _("Nivel de verbosidad:"), verbosity.LEVEL_CHOICES),
			S.Choice("tutorMessages", _("Mensajes de tutor (pistas de uso):"), _TUTOR),
			S.Int("tutorMessagesDelay", _("Retardo de los mensajes de tutor (milisegundos):"), 0, 10000),
		]

	def makeExtraSettings(self, builder: S.SettingsBuilder) -> None:
		from ..speech import verbosity

		self._order = verbosity.getOrder()
		self._originalOrder = list(self._order)
		g = builder.group(_("Orden de las propiedades al anunciar un control"))
		self.orderList = g.addLabeledControl(
			_("Propi&edades (en el orden en que se dicen):"),
			lambda p: wx.ListBox(p, choices=[verbosity.PROPERTY_LABELS[k] for k in self._order], size=(300, 140)),
			vertical=True,
		)
		if self._order:
			self.orderList.SetSelection(0)
		row = wx.BoxSizer(wx.HORIZONTAL)
		up = wx.Button(g.parent, label=_("&Subir"))
		down = wx.Button(g.parent, label=_("&Bajar"))
		reset = wx.Button(g.parent, label=_("Orden &normal"))
		for b in (up, down, reset):
			row.Add(b, 0, wx.RIGHT, 6)
		g.sizer.Add(row, 0, wx.BOTTOM, 4)
		up.Bind(wx.EVT_BUTTON, lambda evt: self._move(-1))
		down.Bind(wx.EVT_BUTTON, lambda evt: self._move(1))
		reset.Bind(wx.EVT_BUTTON, lambda evt: self._resetOrder())
		self._orderLocked = self.lockControls("presentation", "propertyOrder", self.orderList, up, down, reset)
		btn = builder.addButton(_("Plantillas de anuncio por &tipo de control..."))
		btn.Bind(wx.EVT_BUTTON, lambda evt: _openSpeechDialog("showRoleTemplates"))
		self._helpKeys = {c: ("presentation", "propertyOrder") for c in (self.orderList, up, down, reset)}
		self._helpKeys[btn] = ("presentation", "roleTemplates")

	def resetExtraToFactory(self) -> None:
		if not self._orderLocked:
			self._resetOrder()

	def _fillOrder(self, select: int) -> None:
		from ..speech import verbosity

		self.orderList.Set([verbosity.PROPERTY_LABELS[k] for k in self._order])
		self.orderList.SetSelection(max(0, min(select, len(self._order) - 1)))

	def _move(self, direction: int) -> None:
		i = self.orderList.GetSelection()
		j = i + direction
		if i < 0 or not 0 <= j < len(self._order):
			wx.Bell()
			return
		self._order[i], self._order[j] = self._order[j], self._order[i]
		self._fillOrder(j)
		self.orderList.SetFocus()

	def _resetOrder(self) -> None:
		from ..speech import verbosity

		self._order = list(verbosity.DEFAULT_ORDER)
		self._fillOrder(0)

	def onSave(self) -> None:
		super().onSave()
		if not self._orderLocked and self._order != self._originalOrder:
			conf["presentation"]["propertyOrder"] = list(self._order)
			self._originalOrder = list(self._order)


#: Últimas voces leídas en el núcleo (para construir el panel sin tocar el sintetizador).
_voiceChoicesCache: list[tuple[str, str]] | None = None


def _cachedVoiceChoices() -> list[tuple[str, str]]:
	if _voiceChoicesCache:
		return list(_voiceChoicesCache)
	return [("", _("La misma voz"))]


def _openSpeechDialog(name: str, onClose: Any = None) -> None:
	from . import speech_dialogs

	if onClose is None:
		getattr(speech_dialogs, name)()
	else:
		getattr(speech_dialogs, name)(onClose=onClose)


_PANELS = [
	("speechReading", SpeechReadingPanel),
	("speechLanguage", SpeechLanguagePanel),
	("voiceContexts", VoiceContextsPanel),
	("verbosity", VerbosityPanel),
]


def registerPanels() -> None:
	"""Añade las categorías (su sitio en la lista lo da ``settings.getPanelIds``)."""
	for pid, cls in _PANELS:
		S.registerPanel(pid, cls.title, cls)
