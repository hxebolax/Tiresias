"""Eclipse y entornos basados en él (DBeaver, Spring Tool Suite, Zend Studio).

- Lee el elemento seleccionado del asistente de contenido (Control+Espacio)
  mientras el foco sigue en el editor.
- Lee la línea resultante tras Control+D (borrar línea), Alt+flechas (mover
  líneas) y Control+Alt+flechas (duplicar líneas).
"""

from __future__ import annotations

from ._ide import IDEAppModule


class AppModule(IDEAppModule):
	completionListNames = ("content assist", "asistente de contenido", "completion", "proposals", "propuestas")
