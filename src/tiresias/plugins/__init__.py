"""Complementos globales (plugins).

Un complemento global está activo en todas las aplicaciones. Se define en
la carpeta ``globalPlugins`` de un complemento con una clase
``GlobalPlugin``::

	from tiresias.plugins import GlobalPlugin as Base
	from tiresias.baseobject import script

	class GlobalPlugin(Base):
		@script(description="Dice la hora", gesture="kb:tiresias+shift+h")
		def script_hora(self, gesture):
			...

		def event_gainFocus(self, obj, nextHandler):
			nextHandler()
"""

from __future__ import annotations

from ..baseobject import ScriptableObject


class GlobalPlugin(ScriptableObject):
	def __init__(self) -> None:
		super().__init__()

	def chooseObjectClass(self, obj, clsList: list[type]) -> None:
		"""Permite añadir clases superpuestas a cualquier objeto."""

	def terminate(self) -> None:
		"""Se llama al descargar el complemento."""
