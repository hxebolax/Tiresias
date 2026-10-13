"""Bloc de notas de Windows 11.

- Tiresias+Fin lee la barra de estado (línea, columna, caracteres,
  codificación...): en el Bloc de notas nuevo no es una barra de estado UIA
  sino un grupo de textos.
"""

from __future__ import annotations

from .. import api
from ..log import getLogger
from . import AppModule as BaseAppModule

log = getLogger("notepad")

STATUS_AUTOMATION_ID = "ContentTextBlock"


def statusTexts(fg) -> list[str]:
	from ..a11y import uia_client as uc

	try:
		cond = uc.createPropertyCondition(uc.P_AUTOMATIONID, STATUS_AUTOMATION_ID)
		arr = fg.element.FindAllBuildCache(uc.TreeScope_Descendants, cond, uc.baseCacheRequest)
	except Exception:
		log.debug("No se encontró la barra de estado del Bloc de notas", exc_info=True)
		return []
	out = []
	for i in range(arr.Length if arr else 0):
		try:
			name = arr.GetElement(i).CachedName or ""
		except Exception:
			name = ""
		name = " ".join(name.split())
		if name:
			out.append(name)
	return out


class AppModule(BaseAppModule):
	def getStatusBarText(self) -> str | None:
		fg = api.getForegroundObject()
		if fg is None or not hasattr(fg, "element"):
			return None
		texts = statusTexts(fg)
		return ", ".join(texts) if texts else None
