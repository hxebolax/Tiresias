"""Pantalla de bloqueo de Windows (``LockApp``).

Por seguridad, mientras la pantalla de bloqueo está activa el objeto
navegador no puede salir de ella: si el usuario intenta navegar a una
ventana de su escritorio (que está debajo, bloqueado), Tiresias vuelve al
foco y lo avisa. Así no se puede leer el contenido de la sesión bloqueada.
"""

from __future__ import annotations

from .. import api, speech
from ..i18n import _
from ..log import getLogger
from . import AppModule as BaseAppModule

log = getLogger("lockapp")

_active: "AppModule | None" = None
_guard = False


def _onNavigatorChange(obj=None) -> None:
	"""No deja que el navegador salga de la pantalla de bloqueo."""
	global _guard
	app = _active
	if app is None or _guard or obj is None:
		return
	try:
		if not app.isForeground():
			return
		if obj.processID == app.processID:
			return
	except Exception:
		return
	focus = api.getFocusObject()
	_guard = True
	try:
		api.setNavigatorObject(focus)
	finally:
		_guard = False
	speech.speakMessage(_("Fuera de la pantalla de bloqueo"))


class AppModule(BaseAppModule):
	def event_appModule_gainFocus(self) -> None:
		global _active
		_active = self
		api.post_navigatorObjectChange.register(_onNavigatorChange)

	def event_appModule_loseFocus(self) -> None:
		global _active
		if _active is self:
			_active = None
		try:
			api.post_navigatorObjectChange.unregister(_onNavigatorChange)
		except Exception:
			pass

	def terminate(self) -> None:
		self.event_appModule_loseFocus()
