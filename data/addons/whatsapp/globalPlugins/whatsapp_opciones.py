"""Categoría «WhatsApp accesible» en el diálogo de Opciones de Tiresias.

Las mismas casillas que el diálogo de ajustes del complemento
(Alt+Mayúsculas+S dentro de WhatsApp), disponibles siempre que el
complemento esté activado, aunque WhatsApp no se haya abierto todavía.
"""

from __future__ import annotations

from tiresias.log import getLogger
from tiresias.plugins import GlobalPlugin as _Base

from ..appModules import wa_options

log = getLogger("whatsapp")

#: Identificador de la categoría (la ayuda F1 abre el ancla ``cat-whatsapp`` del manual).
PANEL_ID = "whatsapp"


def _panelClass():
	from tiresias.gui import settings as S
	from tiresias.i18n import _

	class WhatsAppPanel(S.ConfigPanel):
		title = _("WhatsApp accesible")
		section = wa_options.SECTION
		fields = [S.Bool(key, label) for key, label in wa_options.SETTINGS]

	return WhatsAppPanel


class GlobalPlugin(_Base):
	def __init__(self) -> None:
		super().__init__()
		wa_options.registerDefaults()
		try:
			from tiresias.gui import settings as S

			cls = _panelClass()
			S.registerPanel(PANEL_ID, cls.title, cls)
		except Exception:
			log.debug("No se pudo añadir la categoría de WhatsApp a las opciones", exc_info=True)

	def terminate(self) -> None:
		try:
			from tiresias.gui import settings as S

			S.unregisterPanel(PANEL_ID)
		except Exception:
			pass
