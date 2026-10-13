"""Administrador de tareas de Windows.

En las listas de procesos, rendimiento, usuarios, detalles y servicios, cada
fila se lee con el valor de sus columnas («CPU 2 %, Memoria 120 MB...»), no
solo con el nombre del proceso.

Nota: el Administrador de tareas se ejecuta con privilegios elevados en las
cuentas de administrador; Tiresias solo lo puede leer si también se ejecuta
como administrador.
"""

from __future__ import annotations

from .. import speech
from ..objects.base import AccObject
from ..objects.roles import Role
from . import AppModule as BaseAppModule


def rowCells(row) -> list[str]:
	"""Valores de las celdas de una fila con el nombre de su columna."""
	parts: list[str] = []
	name = ""
	try:
		name = row.name
		for c in row.children:
			value = c.value or c.name
			if not value or value == name:
				continue
			header = ""
			try:
				header = c.tableHeaders[1]
			except Exception:
				header = ""
			parts.append(f"{header} {value}".strip() if header and header != value else value)
	except Exception:
		pass
	return parts


class TaskManagerRow(AccObject):
	def reportFocus(self) -> None:
		super().reportFocus()
		cells = rowCells(self)
		if cells:
			speech.speakText(", ".join(cells))


class AppModule(BaseAppModule):
	def chooseObjectClass(self, obj, clsList: list[type]) -> None:
		try:
			if obj.role in (Role.DATAITEM, Role.TABLEROW, Role.TREEVIEWITEM) and obj.childCount > 1:
				clsList.insert(0, TaskManagerRow)
		except Exception:
			pass
