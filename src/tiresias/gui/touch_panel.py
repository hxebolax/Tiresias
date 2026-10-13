"""Categoría «Interacción táctil» del cuadro de Opciones."""

from __future__ import annotations

from typing import Any

from .. import queue_handler
from ..i18n import _
from . import settings as S

_TOUCH_TEXT_UNITS = [("character", _("Carácter")), ("word", _("Palabra")), ("line", _("Línea")), ("paragraph", _("Párrafo"))]


class TouchPanel(S.ConfigPanel):
	title = _("Interacción táctil")
	section = "touch"
	fields = [
		S.Bool("enabled", _("&Habilitar la interacción táctil")),
		S.Bool("touchTyping", _("&Escritura táctil: al levantar el dedo sobre una tecla del teclado táctil, se pulsa")),
		S.Choice("textUnit", _("&Unidad de texto bajo el dedo:"), _TOUCH_TEXT_UNITS),
		S.Int("multiTapTimeout", _("&Tiempo máximo entre toques para el doble toque (milisegundos):"), 100, 2000),
		S.Bool("liftedSequentialFlicks", _("Reconocer &secuencias de dos deslizamientos levantando el dedo entre ellos (los deslizamientos simples tardan un poco más)")),
		S.Bool("edgeGestures", _("Gestos de &borde: los deslizamientos que empiezan junto a un borde de la pantalla tienen órdenes propias")),
		S.Int("edgeMargin", _("&Anchura de la franja de cada borde (píxeles):"), 4, 200),
		S.Bool("touchpadEnabled", _("Reconocer gestos en el pa&nel táctil (touchpad) de precisión")),
		S.Bool("touchpadSingleFinger", _("Reconocer también los gestos de un &dedo en el panel táctil")),
	]

	def makeHeaderSettings(self, builder: S.SettingsBuilder) -> None:
		from ..touch import win32

		present, maxTouches = win32.touchHardware()
		if present:
			text = _("Pantalla táctil detectada ({n} contactos como máximo).").format(n=maxTouches)
		else:
			text = _("No se ha detectado ninguna pantalla táctil: la interacción táctil no se activará aunque esté marcada.")
		builder.addStaticText(text)

	def afterSave(self, changes: dict[tuple[str, str], tuple[Any, Any]]) -> None:
		from ..touch.handler import handler

		restart = any(("touch", k) in changes for k in ("multiTapTimeout", "edgeGestures", "edgeMargin"))
		queue_handler.queueFunction(handler.reload if restart else handler.apply)


def register() -> None:
	"""Añade la categoría (va después de «Ratón»; ver ``settings.PANEL_ORDER``)."""
	S.registerPanel("touch", TouchPanel.title, TouchPanel)
