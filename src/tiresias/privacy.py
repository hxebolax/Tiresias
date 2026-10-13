"""Protección de lo que se escribe: campos de contraseña y registro de teclas.

- :func:`isProtected`: un objeto es un campo protegido si su rol es
  «edición de contraseña» o tiene el estado «protegido» (``STATE_PROTECTED``
  de MSAA o ``IsPassword`` de UIA), como ``NVDAObject.isProtected``. Si no
  se puede saber (el objeto ya no existe, COM falla), se trata como
  protegido: ante la duda no se dice lo escrito.
- :func:`gestureLogName`: nombre de una tecla para el registro de
  depuración sin el carácter escrito (así el registro no guarda contraseñas
  ni nada de lo que se teclea).
"""

from __future__ import annotations

from typing import Any


def isProtected(obj: Any) -> bool:
	"""``True`` si lo que se escribe en ``obj`` no debe decirse ni mostrarse.

	``obj`` ``None`` no es protegido; cualquier error al leerlo, sí.
	"""
	if obj is None:
		return False
	from .objects.roles import Role, State

	try:
		if obj.role == Role.PASSWORDEDIT:
			return True
	except AttributeError:
		return False
	except Exception:
		# El objeto ya no existe o COM falla: ante la duda, protegido.
		return True
	try:
		states = obj.states
	except AttributeError:
		# Objetos sin estados (simulados o de complementos): solo cuenta el rol.
		return False
	except Exception:
		return True
	try:
		return bool(states) and State.PROTECTED in states
	except Exception:
		return True


def gestureLogName(gesture: Any) -> str:
	"""Identificador para el registro: las teclas de carácter salen como ``kb:<carácter>``."""
	try:
		ident = gesture.identifiers[-1]
	except Exception:
		return "?"
	mods = set(getattr(gesture, "modifiers", ()) or ()) - {"shift"}
	if mods:
		return ident
	main = str(getattr(gesture, "mainKeyName", "") or "")
	char = getattr(gesture, "char", None)
	if (char and str(char).isprintable() and not str(char).isspace()) or len(main) == 1 or main.startswith("numpad") and main[6:].isdigit():
		return "kb:<carácter>"
	return ident
