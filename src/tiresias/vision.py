"""Mejoras visuales: cortina de pantalla y resaltado.

- La cortina de pantalla pone la pantalla en negro (privacidad) con la API
  de ampliación de Windows; el lector sigue funcionando y el OCR también
  (las capturas se componen ventana a ventana, #19164). Al activarla puede
  pedir confirmación y suena un sonido opcional; al arrancar con la cortina
  activada se anuncia su estado aunque los sonidos estén desactivados (#10692).
- El resaltado dibuja a la vez varios rectángulos de colores: foco del
  sistema, objeto navegador, cursor del modo exploración y objeto bajo el
  ratón (#17576). Se refresca periódicamente porque los objetos se mueven
  (desplazamiento, ventanas que cambian de tamaño).
"""

from __future__ import annotations

import ctypes
from typing import Any

from . import api, queue_handler, speech
from .audio import tones
from .config import conf, registerDefaults
from .i18n import _
from .log import getLogger

log = getLogger("vision")

registerDefaults(
	"vision",
	{
		"screenCurtain": False,
		"curtainWarnOnEnable": True,
		"curtainPlaySounds": True,
		"curtainReportAtStartup": True,
		"highlightFocus": False,
		"highlightNavigator": False,
		"highlightBrowseMode": False,
		"highlightMouse": False,
		"highlightColor": "#FF0000",
		"highlightNavigatorColor": "#FF00FF",
		"highlightBrowseModeColor": "#FFC000",
		"highlightMouseColor": "#00B000",
		"highlightThickness": 4,
		"highlightPadding": 2,
		"highlightRefreshInterval": 500,
	},
)

HIGHLIGHT_KINDS = ("focus", "navigator", "browseMode", "mouse")
_ENABLE_KEYS = {"focus": "highlightFocus", "navigator": "highlightNavigator", "browseMode": "highlightBrowseMode", "mouse": "highlightMouse"}
_COLOR_KEYS = {"focus": "highlightColor", "navigator": "highlightNavigatorColor", "browseMode": "highlightBrowseModeColor", "mouse": "highlightMouseColor"}
KIND_LABELS = {"focus": _("foco"), "navigator": _("objeto navegador"), "browseMode": _("cursor del modo exploración"), "mouse": _("ratón")}


# La misma estructura que declara la lupa en los argtypes de Magnification.dll:
# una clase propia con los mismos campos sería otro tipo para ctypes y la
# llamada fallaría («expected LP_MAGCOLOREFFECT instance»), sin cortina.
from .magnifier import MAGCOLOREFFECT  # noqa: E402

# Todo a cero salvo la opacidad (fila 4, columna 4) y la componente afín
# (fila 5, columna 5): si la opacidad también fuera cero, algunas tarjetas
# gráficas no dejan la pantalla en negro.
_BLACK = MAGCOLOREFFECT((ctypes.c_float * 25)(*([0.0] * 18 + [1.0] + [0.0] * 5 + [1.0])))


def computeHighlights(rects: dict[str, tuple[int, int, int, int] | None], padding: int = 0) -> dict[str, tuple[int, int, int, int]]:
	"""Rectángulos que hay que dibujar, sin repetir uno igual a otro ya dibujado.

	El orden de prioridad es el de ``HIGHLIGHT_KINDS``: si el navegador está
	sobre el foco solo se dibuja el del foco.
	"""
	out: dict[str, tuple[int, int, int, int]] = {}
	seen: set[tuple[int, int, int, int]] = set()
	for kind in HIGHLIGHT_KINDS:
		r = rects.get(kind)
		if not r:
			continue
		x, y, w, h = (int(v) for v in r)
		if w <= 0 or h <= 0:
			continue
		if (x, y, w, h) in seen:
			continue
		seen.add((x, y, w, h))
		out[kind] = (x - padding, y - padding, w + 2 * padding, h + 2 * padding)
	return out


class VisionHandler:
	def __init__(self) -> None:
		self.curtainActive = False
		#: La cortina tiene tomada una referencia de la API de ampliación (hilo de la interfaz).
		self._curtainAcquired = False
		self._refreshTimer: int | None = None
		self._drawn: dict[str, tuple[int, int, int, int]] = {}

	# --------------------------------------------------------- cortina
	def _applyCurtain(self, enable: bool) -> bool:
		"""Aplica o quita la cortina (hilo de la interfaz).

		``_curtainAcquired`` es la marca propia de este hilo: dice si la cortina
		tiene tomada una referencia de la API de ampliación. ``curtainActive`` se
		actualiza después en el hilo del núcleo, así que dos activaciones seguidas
		la verían aún a ``False`` y tomarían dos referencias.
		"""
		from .magnifier import magApi, magnifier

		mag = magApi.dll()
		if enable:
			if self._curtainAcquired:
				return True
			if not magApi.acquire():
				return False
			if not mag.MagSetFullscreenColorEffect(ctypes.byref(_BLACK)):
				# Sin cortina no se conserva la referencia.
				magApi.release()
				return False
			self._curtainAcquired = True
			return True
		if not self._curtainAcquired:
			return True
		from .magnifier import filterEffect

		ok = bool(mag.MagSetFullscreenColorEffect(ctypes.byref(filterEffect("none"))))
		magApi.release()
		self._curtainAcquired = False
		# Si la lupa tenía un filtro de color, se recupera.
		self.curtainActive = False
		if magnifier.active:
			magnifier._applyColors()
		return ok

	def setScreenCurtain(self, enable: bool, announce: bool = True, startup: bool = False) -> None:
		from . import gui

		def apply() -> None:
			ok = False
			try:
				ok = self._applyCurtain(enable)
			except OSError:
				log.exception("API de ampliación no disponible")
			queue_handler.queueFunction(self._afterCurtain, enable, ok, announce, startup)

		gui.runOnGui(apply)

	def _afterCurtain(self, enable: bool, ok: bool, announce: bool, startup: bool = False) -> None:
		if not ok:
			if announce or startup:
				speech.speakMessage(_("No se pudo cambiar la cortina de pantalla. Puede requerir ejecutar Tiresias como administrador."))
			return
		self.curtainActive = enable
		# La orden y las opciones dejan la cortina guardada en la configuración.
		if conf["vision"]["screenCurtain"] != enable:
			conf["vision"]["screenCurtain"] = enable
		if startup:
			# #10692: el estado se anuncia al arrancar aunque no haya sonidos.
			if enable and conf["vision"]["curtainReportAtStartup"]:
				speech.speakMessage(_("Cortina de pantalla activada"))
			return
		if announce:
			if conf["vision"]["curtainPlaySounds"]:
				tones.playSound("screenCurtainOn" if enable else "screenCurtainOff")
			speech.speakMessage(_("Cortina de pantalla activada") if enable else _("Cortina de pantalla desactivada"))

	def curtainStateText(self) -> str:
		return _("Cortina de pantalla activada") if self.curtainActive else _("Cortina de pantalla desactivada")

	def toggleScreenCurtain(self) -> None:
		if self.curtainActive:
			self.setScreenCurtain(False)
			return
		if conf["vision"]["curtainWarnOnEnable"]:
			self._confirmCurtain()
		else:
			self.setScreenCurtain(True)

	def _confirmCurtain(self) -> None:
		"""Avisa antes de oscurecer la pantalla, con opción de no volver a preguntar."""
		from .gui import helpers

		def ask() -> None:
			import wx

			from .gui import message_dialog

			# Cuadro propio con el texto recorrible (#258).
			dlg = message_dialog.MessageDialog(
				None,
				_("La cortina de pantalla pone la pantalla en negro: nadie verá lo que haces, tampoco tú. Tiresias y el OCR siguen funcionando. Para quitarla vuelve a pulsar la misma orden. ¿Activar la cortina?"),
				_("Cortina de pantalla"),
				wx.YES_NO | wx.ICON_WARNING,
			)
			dlg.ShowCheckBox(_("No volver a preguntar"))
			result = dlg.ShowModal()
			dontAsk = dlg.IsCheckBoxChecked()
			dlg.Destroy()
			if result == wx.ID_YES:
				if dontAsk:
					conf["vision"]["curtainWarnOnEnable"] = False
				queue_handler.queueFunction(self.setScreenCurtain, True)

		helpers.runOnGui(ask)

	# --------------------------------------------------------- resaltado
	def anyHighlight(self) -> bool:
		v = conf["vision"]
		return any(v[_ENABLE_KEYS[k]] for k in HIGHLIGHT_KINDS)

	def toggleHighlight(self) -> None:
		v = not self.anyHighlight()
		conf["vision"]["highlightFocus"] = v
		conf["vision"]["highlightNavigator"] = v
		conf["vision"]["highlightBrowseMode"] = v
		if not v:
			conf["vision"]["highlightMouse"] = False
		speech.speakMessage(_("Resaltado visual activado") if v else _("Resaltado visual desactivado"))
		self.refresh()

	def toggleHighlightKind(self, kind: str) -> None:
		key = _ENABLE_KEYS[kind]
		v = not conf["vision"][key]
		conf["vision"][key] = v
		speech.speakMessage((_("Resaltado del {what} activado") if v else _("Resaltado del {what} desactivado")).format(what=KIND_LABELS[kind]))
		self.refresh()

	@staticmethod
	def _location(obj: Any) -> tuple[int, int, int, int] | None:
		if obj is None:
			return None
		try:
			return obj.location
		except Exception:
			return None

	def _browseRect(self) -> tuple[int, int, int, int] | None:
		try:
			caret = api.getCaretObject()
			if caret is not None and getattr(caret, "buffer", None) and not caret.passThrough:
				from .browse.buffer import liveNodeRect

				# Posición actual del elemento: la guardada al construir el búfer se
				# queda desfasada al desplazar la página.
				node = caret.buffer.nodeAt(caret.caret)
				while node is not None:
					rect = liveNodeRect(node)
					if rect:
						return rect
					node = node.parent
		except Exception:
			log.debug("Sin rectángulo del modo exploración", exc_info=True)
		return None

	def currentRects(self) -> dict[str, tuple[int, int, int, int] | None]:
		v = conf["vision"]
		rects: dict[str, tuple[int, int, int, int] | None] = {}
		if v["highlightBrowseMode"]:
			rects["browseMode"] = self._browseRect()
		if v["highlightFocus"]:
			focus = api.getFocusObject()
			# En modo exploración el foco es el documento entero: se resalta el cursor.
			if rects.get("browseMode") is None:
				rects["focus"] = self._location(focus)
		if v["highlightNavigator"]:
			rects["navigator"] = self._location(api.getNavigatorObject())
		if v["highlightMouse"]:
			rects["mouse"] = self._location(api.getMouseObject())
		return rects

	def refresh(self) -> None:
		"""Recalcula y dibuja los rectángulos (hilo del núcleo)."""
		from .gui import highlighter

		v = conf["vision"]
		if not self.anyHighlight():
			if self._drawn:
				highlighter.hideAll()
				self._drawn = {}
			self._cancelTimer()
			return
		wanted = computeHighlights(self.currentRects(), max(0, int(v["highlightPadding"])))
		thickness = int(v["highlightThickness"])
		for kind in HIGHLIGHT_KINDS:
			if kind in wanted:
				if self._drawn.get(kind) != wanted[kind]:
					highlighter.show(wanted[kind], v[_COLOR_KEYS[kind]], thickness, group=kind)
			elif kind in self._drawn:
				highlighter.hide(group=kind)
		self._drawn = wanted
		self._scheduleRefresh()

	def forceRedraw(self) -> None:
		"""Vuelve a dibujar todo (tras cambiar colores o grosor)."""
		from .gui import highlighter

		highlighter.hideAll()
		self._drawn = {}
		self.refresh()

	def _cancelTimer(self) -> None:
		if self._refreshTimer is not None:
			queue_handler.cancelCallLater(self._refreshTimer)
			self._refreshTimer = None

	def _scheduleRefresh(self) -> None:
		self._cancelTimer()
		interval = int(conf["vision"]["highlightRefreshInterval"])
		if interval > 0:
			self._refreshTimer = queue_handler.callLater(max(100, interval), self._onTimer)

	def _onTimer(self) -> None:
		self._refreshTimer = None
		try:
			self.refresh()
		except Exception:
			log.debug("Error refrescando el resaltado", exc_info=True)

	def onNavigatorChange(self, obj: Any = None) -> None:
		if conf["vision"]["highlightNavigator"]:
			self.refresh()

	def onFocusChange(self, obj: Any = None) -> None:
		if self.anyHighlight():
			self.refresh()

	def onReviewMove(self, info: Any = None, isCaret: bool = False) -> None:
		v = conf["vision"]
		if v["highlightBrowseMode"] or v["highlightNavigator"]:
			self.refresh()

	def initialize(self) -> None:
		api.post_focusChange.register(self.onFocusChange)
		api.post_reviewMove.register(self.onReviewMove)
		api.post_navigatorObjectChange.register(self.onNavigatorChange)
		if conf["vision"]["screenCurtain"]:
			self.setScreenCurtain(True, announce=False, startup=True)
		if self.anyHighlight():
			queue_handler.callLater(500, self.refresh)

	def terminate(self) -> None:
		self._cancelTimer()
		if self.curtainActive or self._curtainAcquired:
			from .magnifier import runOnGuiAndWait

			def off() -> None:
				try:
					self._applyCurtain(False)
				except Exception:
					pass

			runOnGuiAndWait(off)
		try:
			from .gui import highlighter

			highlighter.destroy()
		except Exception:
			pass


handler = VisionHandler()
