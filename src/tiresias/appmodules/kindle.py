"""Kindle para PC.

- Al pasar de página en un libro (Av Pág y Re Pág) se lee la página nueva
  desde el principio, como al abrirlo.
- El libro se lee con el modo exploración (Tiresias+Espacio lo alterna); la
  biblioteca y los menús, en modo foco.
"""

from __future__ import annotations

from .. import api, queue_handler, textinfo
from ..baseobject import normalizeGestureId
from ..i18n import _
from ..objects.roles import Role
from . import AppModule as BaseAppModule

CAT = _("Kindle")

PAGE_KEYS = ("kb:pageDown", "kb:pageUp")


def inBook() -> bool:
	"""``True`` si el foco está en el contenido de un libro (un documento)."""
	focus = api.getFocusObject()
	try:
		if focus is None:
			return False
		if focus.role == Role.DOCUMENT:
			return True
		ti = focus.treeInterceptor
		return ti is not None and not ti.passThrough
	except Exception:
		return False


class AppModule(BaseAppModule):
	scriptCategory = CAT

	def script_turnPage(self, gesture) -> None:
		if not inBook():
			gesture.send()
			return
		gesture.send()

		def readPage() -> None:
			from ..speech import sayall

			try:
				caret = api.getCaretObject()
				info = caret.makeTextInfo(textinfo.POSITION_FIRST)
				info.updateCaret()
			except Exception:
				pass
			sayall.readText(sayall.CURSOR_CARET)

		# La página nueva tarda un momento en dibujarse.
		queue_handler.callLater(500, readPage)

	script_turnPage.__doc__ = _("En un libro: pasa de página y la lee")
	script_turnPage.category = CAT  # type: ignore[attr-defined]


for _g in PAGE_KEYS:
	AppModule._classGestures[normalizeGestureId(_g)] = "turnPage"  # type: ignore[attr-defined]
