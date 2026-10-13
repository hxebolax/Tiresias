"""Microsoft Visual Studio (y SQL Server Management Studio).

- Lee el elemento seleccionado de IntelliSense mientras se escribe.
- Lee la línea resultante tras Control+L (borrar línea), Alt+flechas (mover
  líneas) y atajos parecidos (NVDA #6660).
- Tiresias+Fin lee la barra de estado (línea, columna, carácter...).
"""

from __future__ import annotations

from ._ide import IDEAppModule


class AppModule(IDEAppModule):
	completionListNames = ("completion", "intellisense", "lista de finalización", "lista de miembros")
