"""Categoría «Asistentes de IA» en el diálogo de Opciones de Tiresias."""

from __future__ import annotations

from tiresias.log import getLogger
from tiresias.plugins import GlobalPlugin as _Base

from ..appModules import ia_opciones

log = getLogger("asistentesIA")

#: Identificador de la categoría en las Opciones.
PANEL_ID = "asistentesIA"


def _panelClass():
	from tiresias.gui import settings as S
	from tiresias.i18n import _

	class AsistentesPanel(S.ConfigPanel):
		title = _("Asistentes de IA")
		section = ia_opciones.SECTION
		fields = [S.Bool(key, label) for key, label in ia_opciones.SETTINGS]

	return AsistentesPanel


class GlobalPlugin(_Base):
	def __init__(self) -> None:
		super().__init__()
		ia_opciones.registerDefaults()
		try:
			from tiresias.gui import settings as S

			cls = _panelClass()
			S.registerPanel(PANEL_ID, cls.title, cls)
		except Exception:
			log.debug("No se pudo añadir la categoría a las opciones", exc_info=True)

	def terminate(self) -> None:
		try:
			from tiresias.gui import settings as S

			S.unregisterPanel(PANEL_ID)
		except Exception:
			pass
		super().terminate()
