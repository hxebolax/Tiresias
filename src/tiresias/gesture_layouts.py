"""Mapas de gestos alternativos y exportación del mapa del usuario.

``keyboard.gestureLayout`` elige el mapa:

- ``tiresias``: las teclas propias de Tiresias;
- ``jaws``: añade (por encima de las propias) las combinaciones de JAWS más
  usadas, para quien viene de JAWS (en España, muchos afiliados a la ONCE).
  Las teclas que Tiresias ya comparte con JAWS (Tiresias+T, Tiresias+F12,
  Tiresias+flecha abajo...) no cambian.

El mapa alternativo se aplica como gestos de instancia de las órdenes
globales y del complemento de configuración, así que los cambios que el
usuario haga en «Gestos de entrada» siguen teniendo prioridad.

Todas las teclas del mapa alternativo tienen la prioridad de una orden
global, también las del complemento de configuración (que es el primero de
la cadena): ceden ante la aplicación, el documento y el foco. Así, en una
página web, Tiresias+Espacio sigue cambiando entre modo exploración y modo
foco y Tiresias+V sigue cambiando la disposición en pantalla; fuera de los
documentos abren las capas y los ajustes rápidos (:func:`yieldsToLater`).

También se puede exportar e importar el mapa de gestos del usuario
(``gestures.json``) para llevarlo a otro equipo.
"""

from __future__ import annotations

import json
import os

from .config import conf
from .log import getLogger

log = getLogger("gestureLayouts")

#: Destinos de los gestos: "global" (órdenes globales) o "config" (complemento de configuración).
#: {distribución: {gesto: (destino, orden)}}
LAYOUTS: dict[str, dict[str, tuple[str, str]]] = {
	"tiresias": {},
	"jaws": {
		# Insert+J: ventana de JAWS (menú).
		"kb:tiresias+j": ("global", "showGui"),
		# Insert+F4: salir.
		"kb:tiresias+f4": ("global", "quit"),
		# Insert+F10: lista de ventanas abiertas.
		"kb:tiresias+f10": ("global", "windowList"),
		# Insert+Re Pág: título; Insert+Av Pág: última línea de la ventana (barra de estado).
		"kb:tiresias+pageUp": ("global", "title"),
		"kb:tiresias+pageDown": ("global", "reportStatusLine"),
		# Insert+F1: ayuda sensible a la pantalla (descripción del foco).
		"kb:tiresias+f1": ("global", "reportCurrentFocus"),
		# Insert+F3: lista de órdenes (paleta).
		"kb:tiresias+f3": ("global", "commandPalette"),
		# Insert+V: ajustes rápidos.
		"kb:tiresias+v": ("config", "quickSettings"),
		# Insert+H: lista de teclas rápidas.
		"kb:tiresias+h": ("config", "keyCommandsReference"),
		# Insert+Espacio: teclas por capas.
		"kb:tiresias+space": ("config", "layerKey"),
		# Insert+Z: alternar el cursor virtual (modo exploración/foco) se resuelve en el documento.
		# Insert+Ctrl+F12 / Insert+F12: hora (igual que Tiresias).
		# Insert+Escape: actualizar la pantalla.
		"kb:tiresias+escape": ("config", "refreshScreen"),
		# Las órdenes de Tiresias que estas teclas tapan conservan otra tecla
		# (ninguna se queda sin tecla en ninguna distribución):
		# Tiresias+F10 (copiar desde la marca) pasa a Tiresias+Control+F10.
		"kb:tiresias+control+f10": ("global", "review_copy"),
		# Tiresias+F1 (información técnica del objeto) pasa a Tiresias+Alt+F1.
		"kb:tiresias+alt+f1": ("global", "navigatorObjectDevInfo"),
		# Sobremesa: Tiresias+Re Pág / Av Pág (página de revisión) pasan a
		# Tiresias+Mayúsculas+Re Pág / Av Pág, como en portátil.
		"kb(desktop):tiresias+shift+pageUp": ("global", "review_previousPage"),
		"kb(desktop):tiresias+shift+pageDown": ("global", "review_nextPage"),
		# Portátil: Tiresias+Re Pág / Av Pág (modo de revisión) pasan a
		# Tiresias+Control+Mayúsculas+Alt+Re Pág / Av Pág.
		"kb(laptop):tiresias+control+shift+alt+pageUp": ("global", "reviewMode_next"),
		"kb(laptop):tiresias+control+shift+alt+pageDown": ("global", "reviewMode_previous"),
	},
}

LAYOUT_NAMES = ("tiresias", "jaws")

#: Gestos aplicados actualmente: [(objeto, gesto)].
_applied: list[tuple[object, str]] = []


def layoutLabel(name: str) -> str:
	from .i18n import _

	return {"tiresias": _("Tiresias (propia)"), "jaws": _("Compatible con JAWS")}.get(name, name)


def _targets() -> dict[str, object]:
	from .global_commands import commands

	targets: dict[str, object] = {"global": commands}
	try:
		from . import config_plugin

		if config_plugin.instance is not None:
			targets["config"] = config_plugin.instance
	except Exception:
		pass
	return targets


def apply() -> None:
	"""Aplica el mapa de ``keyboard.gestureLayout`` (hilo del núcleo)."""
	global _applied
	for obj, gid in _applied:
		try:
			inst = obj.__dict__.get("_instanceGestures") or {}
			inst.pop(gid, None)
		except Exception:
			pass
	_applied = []
	try:
		name = conf["keyboard"]["gestureLayout"]
	except KeyError:
		name = "tiresias"
	layout = LAYOUTS.get(name) or {}
	targets = _targets()
	for gid, (target, scriptName) in layout.items():
		obj = targets.get(target)
		if obj is None or getattr(obj, "script_" + scriptName, None) is None:
			log.debug("Orden %s:%s no disponible para %s", target, scriptName, gid)
			continue
		obj.bindGesture(gid, scriptName)
		from .baseobject import normalizeGestureId

		_applied.append((obj, normalizeGestureId(gid)))
	try:
		from .input import core as inputCore

		inputCore.manager.updateChain()
	except Exception:
		pass


def _layoutScriptFor(obj: object, gesture) -> str | None:
	"""Orden del mapa alternativo que ``obj`` atendería para ``gesture`` (o ``None``).

	Devuelve ``None`` si el usuario ha asignado esa tecla en Gestos de entrada:
	su asignación manda y se respeta tal cual.
	"""
	from .baseobject import normalizeGestureId
	from .input import gestures as gestureMap

	applied = {gid for o, gid in _applied if o is obj}
	if not applied:
		return None
	inst = getattr(obj, "__dict__", {}).get("_instanceGestures") or {}
	ids = [normalizeGestureId(gid) for gid in getattr(gesture, "identifiers", ()) or ()]
	# Misma prioridad que ScriptableObject.getScript: usuario, instancia y clase.
	if any(gestureMap.userMap.lookup(type(obj), n) is not None for n in ids):
		return None
	for n in ids:
		if n in inst:
			return inst[n] if n in applied and inst[n] else None
	return None


def yieldsToLater(obj: object, gesture) -> bool:
	"""``True`` si ``gesture`` es una tecla del mapa alternativo que debe ceder.

	Las teclas del mapa se atienden con la prioridad de las órdenes globales:
	si la aplicación, el documento (modo exploración o foco) o el foco tienen
	una orden propia para esa tecla, se usa la suya. Se llama desde
	``getScript`` del objeto que recibe la asignación (hilo del núcleo).
	"""
	if _layoutScriptFor(obj, gesture) is None:
		return False
	try:
		from .global_commands import commands as globalCommands
		from .input import core as inputCore

		chain = list(inputCore.manager.chain)
	except Exception:
		return False
	try:
		idx = next(i for i, o in enumerate(chain) if o is obj)
	except StopIteration:
		return False
	for later in chain[idx + 1 :]:
		if later is globalCommands:
			break
		try:
			if later.getScript(gesture):
				return True
		except Exception:
			log.debug("Error consultando %r", later, exc_info=True)
	return False


# ====================================================================== exportar e importar
EXPORT_FORMAT = "tiresias-gestos"


def exportUserMap(fileName: str) -> int:
	"""Guarda el mapa de gestos del usuario en ``fileName``. Devuelve el número de gestos."""
	from .input import gestures

	data = gestures.userMap.userBindings()
	count = sum(len(v) for v in data.values())
	with open(fileName, "w", encoding="utf-8") as f:
		json.dump({"format": EXPORT_FORMAT, "version": 1, "gestureLayout": conf["keyboard"]["gestureLayout"], "bindings": data}, f, ensure_ascii=False, indent="\t", sort_keys=True)
	return count


def readExport(fileName: str) -> dict[str, dict[str, str | None]]:
	"""Lee un archivo exportado (también acepta un ``gestures.json`` directamente)."""
	with open(fileName, encoding="utf-8-sig") as f:
		data = json.load(f)
	if not isinstance(data, dict):
		raise ValueError("formato no válido")
	bindings = data.get("bindings") if data.get("format") == EXPORT_FORMAT else data
	if not isinstance(bindings, dict):
		raise ValueError("formato no válido")
	out: dict[str, dict[str, str | None]] = {}
	for cls, m in bindings.items():
		if not isinstance(m, dict):
			continue
		out[str(cls)] = {str(g): (s if isinstance(s, str) else None) for g, s in m.items()}
	return out


def importUserMap(fileName: str, merge: bool = True) -> int:
	"""Importa un mapa de gestos. ``merge``: conservar los cambios actuales que no choquen."""
	from .input import gestures

	new = readExport(fileName)
	m = gestures.userMap
	if not merge:
		m.reset()
	count = 0
	for cls, bindings in new.items():
		for gid, scriptName in bindings.items():
			if scriptName is None:
				m.unbind(cls, gid)
			else:
				m.bind(cls, gid, scriptName)
			count += 1
	m.save()
	try:
		from .input import core as inputCore

		inputCore.manager.updateChain()
	except Exception:
		pass
	return count


def defaultExportName() -> str:
	return os.path.join(os.path.expanduser("~"), "Documents", "gestos-tiresias.json")
