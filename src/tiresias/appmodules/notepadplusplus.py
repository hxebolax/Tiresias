"""Notepad++ (ejecutable ``notepad++.exe``, asociado en ``EXECUTABLE_ALIASES``).

- El editor Scintilla se lee como un campo de edición normal (cursor,
  selección, líneas, lectura continua) mediante los mensajes de Scintilla.
- Se leen los elementos de las listas de autocompletado al recorrerlas.
- Tiresias+Fin lee la barra de estado (línea, columna, codificación...).
"""

from __future__ import annotations

from .. import presentation
from ..objects.roles import Role
from . import AppModule as BaseAppModule
from . import _scintilla


class AppModule(BaseAppModule):
	def chooseObjectClass(self, obj, clsList: list[type]) -> None:
		if _scintilla.isScintilla(obj):
			for i, cls in enumerate(_scintilla.overlayClasses()):
				if cls not in clsList:
					clsList.insert(i, cls)

	def event_selection(self, obj, nextHandler) -> None:
		# Lista de autocompletado: cambia la selección sin mover el foco.
		try:
			from .. import api

			focus = api.getFocusObject()
			if focus is not None and obj == focus:
				# El elemento ya tiene el foco y se anunció (lista de archivos del
				# diálogo Abrir...): no se repite.
				return
			if obj.role == Role.LISTITEM and obj.name:
				presentation.speakObject(obj, reason=presentation.Reason.FOCUS)
				return
		except Exception:
			pass
		nextHandler()
