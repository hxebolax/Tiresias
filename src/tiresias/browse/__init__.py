"""Modo exploración (documentos web y documentos UIA).

Tipos de documento:

- ``tree``: documentos web (Chrome, Edge, Firefox, WebView2) y Acrobat; el
  búfer se construye con el árbol de elementos UIA.
- ``text``: documentos UIA con patrón Text (Word, panel de lectura de
  Outlook, documentos XAML de solo lectura...); el búfer se construye con el
  texto del documento y sus estilos.

En los documentos editables de Word el modo exploración está disponible con
Tiresias+Espacio, pero se empieza en modo foco y el búfer no se construye
hasta que se pide.
"""

from __future__ import annotations

#: Marcos (FrameworkId de UIA) cuyos documentos usan modo exploración.
BROWSE_MODE_FRAMEWORKS = {"Chrome", "Gecko", "MicrosoftEdge"}

#: Clases de ventana de consolas y terminales (nunca modo exploración).
_TERMINAL_CLASSES = {"ConsoleWindowClass", "TermControl", "WPFTermControl", "PseudoConsoleWindow"}

#: Marcos cuyos documentos de solo lectura con patrón Text usan modo exploración.
TEXT_DOCUMENT_FRAMEWORKS = {"XAML", "WPF", "DirectUI"}

#: Documentos de Word (también en Outlook).
WORD_DOCUMENT_CLASS = "_WwG"


def browseModeKind(obj) -> str | None:
	"""``"tree"``, ``"text"``, ``"lazyText"`` (Word editable) o ``None``."""
	from ..a11y import uia_client as uc
	from ..config import conf
	from ..objects.roles import Role, State

	try:
		if obj.role != Role.DOCUMENT:
			return None
		editable = State.EDITABLE in obj.states
		fw = obj.UIAFrameworkId
		if fw in BROWSE_MODE_FRAMEWORKS:
			return None if editable else "tree"
		if not conf["browseMode"]["uiaDocuments"]:
			return None
		cls = getattr(obj, "UIAClassName", "") or ""
		if cls in _TERMINAL_CLASSES:
			return None
		if cls.startswith("AVL_AVView"):
			# Adobe Acrobat / Reader: árbol de la estructura del PDF.
			return "tree"
		hasText = bool(obj._prop(uc.P_ISTEXTPATTERNAVAILABLE, False))
		if cls == WORD_DOCUMENT_CLASS and hasText:
			# Word no publica el patrón de valor: el estado editable lo calcula
			# el objeto con el atributo IsReadOnly del texto (vista de lectura,
			# vista protegida y panel de lectura de Outlook: modo exploración).
			return "lazyText" if editable else "text"
		if editable or not hasText or fw not in TEXT_DOCUMENT_FRAMEWORKS:
			# Los cuadros de texto de solo lectura de Win32 (licencias, avisos...)
			# se leen mejor con su propio cursor.
			return None
		import os

		if obj.processID == os.getpid():
			return None
		return "text"
	except Exception:
		return None


def shouldUseBrowseMode(obj) -> bool:
	return browseModeKind(obj) is not None
