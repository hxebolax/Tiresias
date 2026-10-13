"""Órdenes de la convivencia con otros lectores de pantalla (complemento incorporado).

Mientras Tiresias está en espera no hay ganchos de teclado, así que estas
órdenes solo sirven con Tiresias activo. Para activarlo desde la espera
están el menú del icono y Control+Alt+Mayúsculas+T (ver :mod:`.ui`).
"""

from __future__ import annotations

from .. import speech
from ..baseobject import script
from ..i18n import _
from ..plugins import GlobalPlugin

CAT_COEXIST = _("Convivencia con otros lectores")


class CoexistGlobalPlugin(GlobalPlugin):
	@script(
		description=_("Cede el paso al otro lector de pantalla en ejecución: Tiresias pasa a espera hasta que ese lector se cierre"),
		category=CAT_COEXIST,
		gesture="kb:tiresias+control+shift+e",
	)
	def script_coexistYield(self, gesture) -> None:
		from .. import coexist

		if not coexist.runningReaders():
			speech.speakMessage(_("No hay ningún otro lector de pantalla activo"))
			return
		# El anuncio lo hace el otro lector cuando Tiresias ya está en espera.
		coexist.yieldNow()

	@script(description=_("Cierra Tiresias e inicia el lector de pantalla recordado (el que usabas antes: NVDA, JAWS, Narrador...)"), category=CAT_COEXIST)
	def script_coexistSwitchBack(self, gesture) -> None:
		from .. import coexist

		coexist.switchToRememberedReader()

	@script(description=_("Informa de los otros lectores de pantalla en ejecución y de si Tiresias les cede el paso"), category=CAT_COEXIST)
	def script_coexistStatus(self, gesture) -> None:
		from .. import coexist

		speech.speakMessage(coexist.statusText())
