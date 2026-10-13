"""foobar2000.

- Anuncia la canción nueva al cambiar (también en segundo plano).
- Control+Mayúsculas+E, R y T: tiempo transcurrido, restante y total de la
  canción (de la barra de estado de foobar2000).
"""

from __future__ import annotations

from .. import api, speech
from ..baseobject import script
from ..i18n import _
from ._media import MediaAppModule, parseElapsedTotal

CAT = _("foobar2000")


class AppModule(MediaAppModule):
	scriptCategory = CAT

	def trackFromTitle(self, title: str) -> str | None:
		# Detenido, el título es «foobar2000 v2.x»; reproduciendo: «Artista - Título [foobar2000]».
		if not title or title.lower().startswith("foobar2000"):
			return None
		for suffix in ("[foobar2000]", "- foobar2000"):
			if title.endswith(suffix):
				title = title[: -len(suffix)].strip()
		return title or None

	def _times(self) -> tuple[int, int] | None:
		bar = api.getStatusBar()
		if bar is None:
			return None
		return parseElapsedTotal(api.statusBarText(bar))

	def _report(self, which: str) -> None:
		t = self._times()
		if t is None:
			speech.speakMessage(_("No se está reproduciendo nada o la barra de estado está oculta"))
			return
		self.speakTimes(which, *t)

	@script(description=_("Tiempo transcurrido de la canción"), category=CAT, gesture="kb:control+shift+e", speakOnDemand=True)
	def script_elapsedTime(self, gesture) -> None:
		self._report("elapsed")

	@script(description=_("Tiempo restante de la canción"), category=CAT, gesture="kb:control+shift+r", speakOnDemand=True)
	def script_remainingTime(self, gesture) -> None:
		self._report("remaining")

	@script(description=_("Duración total de la canción"), category=CAT, gesture="kb:control+shift+t", speakOnDemand=True)
	def script_totalTime(self, gesture) -> None:
		self._report("total")
