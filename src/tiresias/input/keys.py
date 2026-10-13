"""Nombres de teclas (internos) y sus etiquetas en español."""

from __future__ import annotations

from .. import winapi

# Teclas cuyo nombre depende del indicador «extendida»:
# vk -> (nombre si extendida, nombre si no extendida)
_EXTENDED_DEPENDENT = {
	0x0D: ("numpadenter", "enter"),
	0x21: ("pageup", "numpad9"),
	0x22: ("pagedown", "numpad3"),
	0x23: ("end", "numpad1"),
	0x24: ("home", "numpad7"),
	0x25: ("leftarrow", "numpad4"),
	0x26: ("uparrow", "numpad8"),
	0x27: ("rightarrow", "numpad6"),
	0x28: ("downarrow", "numpad2"),
	0x2D: ("insert", "numpadinsert"),
	0x2E: ("delete", "numpaddelete"),
	0x0C: ("clear", "numpad5"),
}

_VK_NAMES = {
	0x03: "break",
	0x08: "backspace",
	0x09: "tab",
	0x10: "shift",
	0x11: "control",
	0x12: "alt",
	0x13: "pause",
	0x14: "capslock",
	0x1B: "escape",
	0x20: "space",
	0x2C: "printscreen",
	0x5B: "leftwindows",
	0x5C: "rightwindows",
	0x5D: "applications",
	0x5F: "sleep",
	0x60: "numlocknumpad0",
	0x61: "numlocknumpad1",
	0x62: "numlocknumpad2",
	0x63: "numlocknumpad3",
	0x64: "numlocknumpad4",
	0x65: "numlocknumpad5",
	0x66: "numlocknumpad6",
	0x67: "numlocknumpad7",
	0x68: "numlocknumpad8",
	0x69: "numlocknumpad9",
	0x6A: "numpadmultiply",
	0x6B: "numpadplus",
	0x6C: "numpadseparator",
	0x6D: "numpadminus",
	0x6E: "numpaddecimal",
	0x6F: "numpaddivide",
	0x90: "numlock",
	0x91: "scrolllock",
	0xA0: "leftshift",
	0xA1: "rightshift",
	0xA2: "leftcontrol",
	0xA3: "rightcontrol",
	0xA4: "leftalt",
	0xA5: "rightalt",
	0xA6: "browserback",
	0xA7: "browserforward",
	0xA8: "browserrefresh",
	0xA9: "browserstop",
	0xAA: "browsersearch",
	0xAB: "browserfavorites",
	0xAC: "browserhome",
	0xAD: "volumemute",
	0xAE: "volumedown",
	0xAF: "volumeup",
	0xB0: "medianexttrack",
	0xB1: "mediaprevtrack",
	0xB2: "mediastop",
	0xB3: "mediaplaypause",
	0xB4: "launchmail",
	0xB5: "launchmediaplayer",
	0xB6: "launchapp1",
	0xB7: "launchapp2",
}
for _i in range(24):
	_VK_NAMES[0x70 + _i] = f"f{_i + 1}"

MODIFIER_VKS = {
	0x10: "shift",
	0xA0: "shift",
	0xA1: "shift",
	0x11: "control",
	0xA2: "control",
	0xA3: "control",
	0x12: "alt",
	0xA4: "alt",
	0xA5: "alt",
	0x5B: "windows",
	0x5C: "windows",
}

_NAME_TO_VK: dict[str, tuple[int, bool]] = {}


def vkName(vk: int, extended: bool, hkl: int | None = None) -> str:
	if vk in _EXTENDED_DEPENDENT:
		ext, normal = _EXTENDED_DEPENDENT[vk]
		return ext if extended else normal
	if vk in _VK_NAMES:
		return _VK_NAMES[vk]
	if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
		return chr(vk).lower()
	# Teclas OEM: el carácter que producen sin modificadores.
	try:
		ch = winapi.user32.MapVirtualKeyExW(vk, 2, hkl) & 0xFFFF
		if ch:
			c = chr(ch).lower()
			# «+» es el separador de los gestos: la tecla se llama «plus».
			return "plus" if c == "+" else c
	except Exception:
		pass
	return f"vk{vk:02x}"


def vkFromName(name: str) -> tuple[int, bool] | None:
	"""Inversa de :func:`vkName` (para enviar teclas). Devuelve (vk, extendida)."""
	if not _NAME_TO_VK:
		for vk, (ext, normal) in _EXTENDED_DEPENDENT.items():
			_NAME_TO_VK[ext] = (vk, True)
			_NAME_TO_VK[normal] = (vk, False)
		for vk, n in _VK_NAMES.items():
			_NAME_TO_VK.setdefault(n, (vk, vk in (0x5B, 0x5C, 0x5D, 0x6F, 0xA3, 0xA5)))
		for vk in list(range(0x30, 0x3A)) + list(range(0x41, 0x5B)):
			_NAME_TO_VK[chr(vk).lower()] = (vk, False)
		_NAME_TO_VK["control"] = (0x11, False)
		_NAME_TO_VK["shift"] = (0x10, False)
		_NAME_TO_VK["alt"] = (0x12, False)
		_NAME_TO_VK["windows"] = (0x5B, True)
	name = name.lower()
	if name in _NAME_TO_VK:
		return _NAME_TO_VK[name]
	if len(name) == 1:
		res = winapi.user32.VkKeyScanW(ord(name)) if hasattr(winapi.user32, "VkKeyScanW") else -1
		if res != -1:
			return (res & 0xFF, False)
	return None


# Etiquetas en español para mostrar o anunciar teclas.
KEY_LABELS = {
	"tiresias": "Tiresias",
	"control": "control",
	"shift": "mayúsculas",
	"alt": "alt",
	"windows": "windows",
	"backspace": "retroceso",
	"tab": "tabulador",
	"enter": "intro",
	"numpadenter": "intro del teclado numérico",
	"escape": "escape",
	"space": "espacio",
	"pageup": "retroceder página",
	"pagedown": "avanzar página",
	"end": "fin",
	"home": "inicio",
	"leftarrow": "flecha izquierda",
	"uparrow": "flecha arriba",
	"rightarrow": "flecha derecha",
	"downarrow": "flecha abajo",
	"insert": "insertar",
	"delete": "suprimir",
	"numpadinsert": "insertar del teclado numérico",
	"numpaddelete": "suprimir del teclado numérico",
	"capslock": "bloqueo de mayúsculas",
	"numlock": "bloqueo numérico",
	"scrolllock": "bloqueo de desplazamiento",
	"printscreen": "imprimir pantalla",
	"pause": "pausa",
	"applications": "aplicaciones",
	"numpadmultiply": "por del teclado numérico",
	"numpadplus": "más del teclado numérico",
	"numpadminus": "menos del teclado numérico",
	"numpaddivide": "barra del teclado numérico",
	"numpaddecimal": "decimal del teclado numérico",
	"leftwindows": "windows izquierda",
	"rightwindows": "windows derecha",
	"volumemute": "silenciar volumen",
	"volumeup": "subir volumen",
	"volumedown": "bajar volumen",
	"mediaplaypause": "reproducir o pausar",
	"medianexttrack": "pista siguiente",
	"mediaprevtrack": "pista anterior",
	"mediastop": "detener",
	",": "coma",
	".": "punto",
	"-": "guion",
	"'": "apóstrofo",
	"+": "más",
	"plus": "más",
	"´": "acento",
	"`": "acento grave",
	"º": "ordinal",
	"<": "menor que",
	"ñ": "eñe",
	"ç": "cedilla",
	"¡": "abre exclamación",
	"[": "abre corchete",
	"]": "cierra corchete",
	"/": "barra",
	"\\": "barra invertida",
	";": "punto y coma",
	"=": "igual",
}
for _i in range(10):
	KEY_LABELS[f"numpad{_i}"] = f"{_i} del teclado numérico"
	KEY_LABELS[f"numlocknumpad{_i}"] = f"{_i} del teclado numérico"
for _i in range(1, 25):
	KEY_LABELS[f"f{_i}"] = f"F{_i}"


KEY_LABELS.update(
	{
		**{f"dot{i}": f"punto {i}" for i in range(1, 9)},
		"leftspace": "espacio izquierdo",
		"rightspace": "espacio derecho",
		"panleft": "desplazar a la izquierda",
		"panright": "desplazar a la derecha",
		"routing": "enrutamiento",
		"joystickup": "joystick arriba",
		"joystickdown": "joystick abajo",
		"joystickleft": "joystick izquierda",
		"joystickright": "joystick derecha",
		"joystickcenter": "joystick centro",
		"dpadup": "cruceta arriba",
		"dpaddown": "cruceta abajo",
		"dpadleft": "cruceta izquierda",
		"dpadright": "cruceta derecha",
		"dpadcenter": "cruceta centro",
		"rockerup": "balancín arriba",
		"rockerdown": "balancín abajo",
		"rockerpress": "pulsar balancín",
	}
)


def labelForKey(name: str) -> str:
	return KEY_LABELS.get(name.lower(), name)


def labelForGesture(gestureId: str) -> str:
	"""``kb:tiresias+control+f`` -> ``Tiresias+control+f``."""
	prefix, _sep, keys = gestureId.partition(":")
	if not keys:
		return gestureId
	if prefix.lower() in ("ts", "tp") or prefix.lower().startswith(("ts(", "tp(")):
		# Pantalla y panel táctil: «pantalla táctil: doble toque (modo objeto)».
		from ..touch.gestures import labelForIdentifier

		return labelForIdentifier(gestureId)
	label = "+".join(labelForKey(k) for k in keys.split("+"))
	if prefix.startswith("br("):
		return f"línea braille: {label}"
	if prefix.startswith("kb(laptop)"):
		label += " (portátil)"
	elif prefix.startswith("kb(desktop)"):
		label += " (sobremesa)"
	return label


winapi.user32.VkKeyScanW.argtypes = [winapi.wintypes.WCHAR]
winapi.user32.VkKeyScanW.restype = winapi.ctypes.c_short
