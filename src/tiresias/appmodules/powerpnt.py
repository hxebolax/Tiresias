"""Microsoft PowerPoint.

- En la lista de miniaturas, cada diapositiva dice si está oculta (NVDA
  #10949) y si tiene notas (NVDA #8049).
- Tiresias+Alt+N lee las notas del orador de la diapositiva actual.
- Tiresias+Supr (Tiresias+Supr del teclado numérico) dice la posición y el
  tamaño de la forma seleccionada en centímetros (NVDA #8024).
- Tiresias+Alt+Mayúsculas+T lee la tabla seleccionada (NVDA #5350) y la celda actual.
- Tiresias+F7: lista de diapositivas, formas, tablas y notas.
- En la presentación a pantalla completa se lee cada diapositiva al pasar.
- Las ecuaciones (OMML) se anuncian («ecuación») y se leen con el motor de
  matemáticas; Tiresias+Alt+E las abre en el explorador de matemáticas
  (foros 3.6, JAWS 2026).
"""

from __future__ import annotations

from .. import api, queue_handler, speech, winapi
from ..baseobject import script
from ..config import conf
from ..i18n import _
from ..log import getLogger
from ..objects.base import AccObject
from ..objects.roles import Role
from . import AppModule as BaseAppModule
from . import _chart, _office, _ppt

log = getLogger("powerpnt")

CAT = _("Microsoft PowerPoint")

SLIDESHOW_KEYS = (
	"kb:pageDown",
	"kb:pageUp",
	"kb:space",
	"kb:enter",
	"kb:backspace",
	"kb:rightArrow",
	"kb:leftArrow",
	"kb:downArrow",
	"kb:upArrow",
	"kb:n",
	"kb:p",
	"kb:home",
	"kb:end",
)


def _repeat() -> int:
	from ..input import core as inputCore

	return inputCore.getLastScriptRepeatCount()


def _fail(error: BaseException) -> None:
	speech.speakMessage(_office.busyMessage(error))


def omWindow(obj) -> int:
	"""Ventana de PowerPoint con modelo de objetos para un objeto cualquiera."""
	try:
		hwnd = obj.windowHandle
	except Exception:
		hwnd = 0
	if hwnd and winapi.getClassName(hwnd) in _ppt.OM_WINDOW_CLASSES:
		return hwnd
	root = winapi.getAncestor(hwnd, winapi.GA_ROOT) if hwnd else winapi.getForegroundWindow()
	for cls in _ppt.OM_WINDOW_CLASSES:
		found = _office.findChildWindow(root, cls)
		if found:
			return found
	return 0


class SlideThumbnail(AccObject):
	"""Miniatura de una diapositiva en el panel de miniaturas."""

	def reportFocus(self) -> None:
		super().reportFocus()
		c = conf["officePowerPoint"]
		if not (c["reportNotesIndicator"] or c["reportHiddenSlides"]):
			return
		slideId = _ppt.slideIdFromAutomationId(getattr(self, "UIAAutomationId", ""))
		if slideId is None:
			return
		rid = getattr(self, "runtimeId", None)
		try:
			from .. import presentation

			already = " ".join(presentation.getObjectSpeech(self, presentation.Reason.FOCUS)).lower()
		except Exception:
			already = ""

		def done(d: dict) -> None:
			focus = api.getFocusObject()
			if focus is None or getattr(focus, "runtimeId", None) != rid:
				return
			parts = []
			# PowerPoint 365 ya dice «Oculta» en el nombre de algunas miniaturas.
			if c["reportHiddenSlides"] and d.get("hidden") and "oculta" not in already and "hidden" not in already:
				parts.append(_("oculta"))
			if c["reportNotesIndicator"] and d.get("notes"):
				parts.append(_("tiene notas"))
			if parts:
				speech.speakMessage(", ".join(parts))

		_office.callAsync(_ppt.om_slideById, omWindow(self), slideId, callback=done, timeout=1.0)


class SlideShowWindow(AccObject):
	"""Presentación a pantalla completa: lee cada diapositiva al cambiar."""

	scriptCategory = CAT

	def _readSlide(self, delay: int = 0) -> None:
		if not conf["officePowerPoint"]["readSlideOnShow"]:
			return
		hwnd = omWindow(self)
		app = self.appModule

		def done(d: dict) -> None:
			key = (d.get("index"), d.get("state"))
			if app is not None and key == getattr(app, "_lastShowSlide", None):
				return
			if app is not None:
				app._lastShowSlide = key
			if d.get("state") == 5:
				speech.cancelSpeech()
				speech.speakMessage(_("Fin de la presentación"))
				return
			speakSlide(hwnd, d, reportNotes=conf["officePowerPoint"]["reportNotesIndicator"])

		def run() -> None:
			_office.callAsync(_ppt.om_slideShowSlide, hwnd, callback=done, timeout=1.5)

		if delay:
			queue_handler.callLater(delay, run)
		else:
			run()

	def reportFocus(self) -> None:
		app = self.appModule
		if app is not None:
			app._lastShowSlide = None
		self._readSlide()

	def script_changeSlide(self, gesture) -> None:
		gesture.send()
		self._readSlide(delay=150)

	script_changeSlide.__doc__ = _("En la presentación: cambia de diapositiva y la lee")
	script_changeSlide.category = CAT  # type: ignore[attr-defined]

	# Las notas al presentar (Tiresias+Alt+N) las lee la orden del módulo de la
	# aplicación, que tiene prioridad sobre las del foco: una orden aquí con el
	# mismo gesto no se ejecutaría nunca.


for _g in SLIDESHOW_KEYS:
	from ..baseobject import normalizeGestureId as _norm

	SlideShowWindow._classGestures[_norm(_g)] = "changeSlide"  # type: ignore[attr-defined]


def speakSlide(hwnd: int, d: dict, **kwargs) -> None:
	"""Lee la diapositiva; si parece tener ecuaciones, las lee con el motor de matemáticas."""
	c = conf["officePowerPoint"]

	def say(equations: dict | None) -> None:
		speech.cancelSpeech()
		speech.speakText(_ppt.slideText(d, equations=equations, speakMath=bool(c["readEquations"]), **kwargs))

	if not d.get("mathSuspect") or not c["readEquations"]:
		say(None)
		return
	_office.callAsync(_ppt.om_slideEquations, hwnd, d.get("id"), _ppt.shapesSignature(d), callback=say, onError=lambda e: say(None), timeout=8)


class AppModule(_chart.ChartNavigationMixin, BaseAppModule):
	scriptCategory = CAT

	def __init__(self, processID: int, appName: str | None = None) -> None:
		super().__init__(processID, appName)
		self._lastShowSlide = None

	def chooseObjectClass(self, obj, clsList: list[type]) -> None:
		try:
			if obj.role == Role.LISTITEM and _ppt.slideIdFromAutomationId(getattr(obj, "UIAAutomationId", "")) is not None:
				clsList.insert(0, SlideThumbnail)
			elif winapi.getClassName(obj.windowHandle) == "screenClass":
				clsList.insert(0, SlideShowWindow)
		except Exception:
			pass

	def _hwnd(self) -> int:
		focus = api.getFocusObject()
		return omWindow(focus) if focus is not None else 0

	@script(description=_("Lee las notas del orador de la diapositiva actual (dos veces: las muestra)"), category=CAT, gesture="kb:tiresias+alt+n", speakOnDemand=True)
	def script_readNotes(self, gesture) -> None:
		show = _repeat() == 1

		def done(d: dict) -> None:
			notes = d.get("notes")
			if not notes:
				speech.speakMessage(_("La diapositiva {n} no tiene notas").format(n=d.get("index")))
			elif show:
				from .. import gui

				gui.showBrowseableMessage(notes, _("Notas de la diapositiva {n}").format(n=d.get("index")))
			else:
				speech.speakText(notes)

		_office.callAsync(_ppt.om_currentSlide, self._hwnd(), callback=done, onError=_fail)

	@script(description=_("Lee la diapositiva actual completa: título, textos, tablas y notas"), category=CAT, gesture="kb:tiresias+alt+shift+l", speakOnDemand=True)
	def script_readSlide(self, gesture) -> None:
		hwnd = self._hwnd()
		_office.callAsync(_ppt.om_currentSlide, hwnd, callback=lambda d: speakSlide(hwnd, d), onError=_fail)

	# ------------------------------------------------------------ ecuaciones (foros 3.6)
	def interactWithMath(self, focus) -> bool:
		"""Tiresias+Alt+E en PowerPoint: abre las ecuaciones de la forma o la diapositiva.

		La llama la orden de matemáticas (``mathpres.plugin``); devuelve ``True``
		porque la busca en segundo plano. Con varias ecuaciones se elige de una lista.
		"""
		hwnd = omWindow(focus) if focus is not None else self._hwnd()
		if not hwnd:
			return False

		def done(res: dict) -> None:
			from .. import mathpres

			items = res.get("items") or []
			if not items:
				speech.speakMessage(_("No hay ecuaciones en la diapositiva {n}").format(n=res.get("slide")))
				return
			if len(items) == 1:
				mathpres.interactWithMathMl(items[0][1])
				return
			from ..gui import app_dialogs

			def go(mathMl: str) -> None:
				queue_handler.callLater(300, mathpres.interactWithMathMl, mathMl)

			app_dialogs.showItemList(
				"pptEquations",
				_("Ecuaciones de la diapositiva {n}").format(n=res.get("slide")),
				[(_("Ecuaciones"), lambda: list(items))],
				[app_dialogs.Action(_("&Explorar"), go, default=True)],
			)

		_office.callAsync(_ppt.om_mathTargets, hwnd, callback=done, onError=_fail, timeout=15)
		return True


	@script(description=_("Anuncia la posición y el tamaño de la forma seleccionada en centímetros"), category=CAT, gestures=("kb(desktop):tiresias+numpadDelete", "kb(laptop):tiresias+delete"), speakOnDemand=True)
	def script_shapeLocation(self, gesture) -> None:
		def done(s) -> None:
			speech.speakMessage(_ppt.shapeLocationText(s) if s else _("No hay ninguna forma seleccionada"))

		_office.callAsync(_ppt.om_selectionShape, self._hwnd(), callback=done, onError=_fail)

	@script(description=_("Lee la tabla seleccionada y la celda actual (dos veces: la muestra en una ventana)"), category=CAT, gesture="kb:tiresias+alt+shift+t", speakOnDemand=True)
	def script_readTable(self, gesture) -> None:
		show = _repeat() == 1

		def done(s) -> None:
			if not s or not s.get("table"):
				speech.speakMessage(_("No hay ninguna tabla seleccionada"))
				return
			rows = s["table"]
			if show:
				from .. import gui

				gui.showBrowseableMessage(_ppt.tableText(rows), s.get("name") or _("Tabla"))
				return
			parts = [_ppt.tableSummary(rows)]
			cell = s.get("cell")
			if cell:
				r, c = cell
				header = rows[0][c - 1] if r > 1 else ""
				parts.append(_("fila {r}, columna {c}").format(r=r, c=c))
				if header:
					parts.append(header)
				parts.append(rows[r - 1][c - 1] or _("en blanco"))
			speech.speakText(", ".join(parts))

		_office.callAsync(_ppt.om_selectionShape, self._hwnd(), callback=done, onError=_fail)

	@script(description=_("Recorre el gráfico seleccionado o de la diapositiva con las flechas (dos veces: lo muestra entero)"), category=CAT, gesture="kb:tiresias+alt+g")
	def script_chart(self, gesture) -> None:
		self.openChart(_chart.om_pptChart, self._hwnd())

	@script(description=_("Lista de diapositivas, formas, tablas y notas de la presentación"), category=CAT, gesture="kb:tiresias+f7")
	def script_elementsList(self, gesture) -> None:
		hwnd = self._hwnd()
		root = winapi.getAncestor(hwnd, winapi.GA_ROOT)
		speech.speakMessage(_("Buscando elementos..."))

		def done(elements: dict) -> None:
			from ..gui import app_dialogs

			def provider(key: str):
				return lambda: list(elements.get(key, []))

			def go(payload) -> None:
				kind, index, name = payload[0], payload[1], payload[2]
				if kind == "table":
					from .. import gui

					gui.showBrowseableMessage(_ppt.tableText(payload[3]), name)
					return

				def onCore() -> None:
					winapi.setForegroundWindow(root)
					if kind == "slide":
						_office.callAsync(_ppt.om_gotoSlide, hwnd, index, callback=lambda d: speech.speakText(_ppt.slideText(d, full=False)), onError=_fail)
					else:
						_office.callAsync(_ppt.om_selectShape, hwnd, index, name, callback=lambda n: speech.speakText(_("{name} seleccionada").format(name=n)), onError=_fail)

				queue_handler.callLater(200, onCore)

			categories = [(label, provider(key)) for key, label in _ppt.ELEMENT_KINDS]
			app_dialogs.showItemList("pptElements", _("Lista de elementos de PowerPoint"), categories, [app_dialogs.Action(_("&Ir"), go, default=True)])

		_office.callAsync(_ppt.om_elements, hwnd, callback=done, onError=_fail, timeout=15)
