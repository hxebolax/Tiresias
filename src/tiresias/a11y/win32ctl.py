"""Acceso a controles Win32 clásicos con mensajes de ventana.

Algunas cosas no se pueden obtener ni con UIA ni con MSAA:

- el cursor y la selección exactos de los campos ``Edit``/``RichEdit`` (y sus
  derivados de Delphi, Visual Basic o Windows Forms) cuando el proveedor
  UIA no ofrece el patrón Text;
- el texto de cada columna de una lista ``SysListView32`` en vista de
  detalles y los encabezados de esas columnas.

Los mensajes que llevan punteros necesitan memoria dentro del proceso de
destino: :class:`RemoteMemory` la reserva con ``VirtualAllocEx`` y la lee con
``ReadProcessMemory``. Se tienen en cuenta los procesos de 32 bits (WOW64),
cuyas estructuras usan punteros de 4 bytes. Todas las llamadas usan
``SendMessageTimeout`` para no bloquear el núcleo si la aplicación no responde.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from ..log import getLogger

log = getLogger("win32ctl")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

ULONG_PTR = ctypes.c_size_t
user32.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM, wintypes.UINT, wintypes.UINT, ctypes.POINTER(ULONG_PTR)]
user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.VirtualAllocEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
kernel32.VirtualAllocEx.restype = ctypes.c_void_p
kernel32.VirtualFreeEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD]
kernel32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.IsWow64Process.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]

SMTO_ABORTIFHUNG = 0x0002
SMTO_BLOCK = 0x0001
MESSAGE_TIMEOUT_MS = 500

PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_READWRITE = 0x04

WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
EM_GETSEL = 0x00B0
EM_SETSEL = 0x00B1
EM_SCROLLCARET = 0x00B7
EM_GETLINECOUNT = 0x00BA
EM_LINEINDEX = 0x00BB
EM_LINELENGTH = 0x00C1
EM_LINEFROMCHAR = 0x00C9
EM_EXGETSEL = 0x0434
EM_EXSETSEL = 0x0437
EM_GETLIMITTEXT = 0x00D5
ES_MULTILINE = 0x0004
ES_PASSWORD = 0x0020
ES_READONLY = 0x0800
GWL_STYLE = -16

LVM_FIRST = 0x1000
LVM_GETITEMCOUNT = LVM_FIRST + 4
LVM_GETNEXTITEM = LVM_FIRST + 12
LVM_GETHEADER = LVM_FIRST + 31
LVM_GETSELECTEDCOUNT = LVM_FIRST + 50
LVM_GETVIEW = LVM_FIRST + 143
LVM_GETITEMTEXTW = LVM_FIRST + 115
LVM_GETCOLUMNORDERARRAY = LVM_FIRST + 59
LVNI_ALL = 0
LVNI_FOCUSED = 1
LVNI_SELECTED = 2
LV_VIEW_DETAILS = 1
TV_FIRST = 0x1100
TVM_GETNEXTITEM = TV_FIRST + 10
TVM_MAPACCIDTOHTREEITEM = TV_FIRST + 42
TVGN_ROOT = 0
TVGN_NEXT = 1
TVGN_PREVIOUS = 2
TVGN_PARENT = 3
TVGN_CHILD = 4
HDM_FIRST = 0x1200
HDM_GETITEMCOUNT = HDM_FIRST + 0
HDM_GETITEMW = HDM_FIRST + 11
HDI_TEXT = 0x0002

#: Clases de ventana de campos de edición que entienden los mensajes EM_*.
EDIT_CLASSES = (
	"edit",
	"richedit",
	"richedit20a",
	"richedit20w",
	"richedit50w",
	"richedit60w",
	"richeditd2dpt",
	"tedit",
	"tmemo",
	"trichedit",
	"tdbedit",
	"tdbmemo",
	"tmaskedit",
	"tspinedit",
	"thundertextbox",
	"thunderrt6textbox",
	"tnewedit",
	"tpasswordedit",
)
_EDIT_PREFIXES = ("windowsforms10.edit.", "windowsforms10.richedit")


def getClassName(hwnd: int) -> str:
	buf = ctypes.create_unicode_buffer(256)
	if not hwnd or not user32.GetClassNameW(hwnd, buf, 256):
		return ""
	return buf.value


def isEditClass(className: str) -> bool:
	c = (className or "").lower()
	return c in EDIT_CLASSES or c.startswith(_EDIT_PREFIXES)


def isRichEditClass(className: str) -> bool:
	c = (className or "").lower()
	return "richedit" in c


def sendMessage(hwnd: int, msg: int, wParam: int = 0, lParam: int = 0, timeout: int = MESSAGE_TIMEOUT_MS) -> int | None:
	"""``SendMessageTimeout``: devuelve el resultado o ``None`` si falla o caduca.

	A las ventanas de la interfaz de Tiresias se les envía desde su propio hilo
	(``own_windows``): si la interfaz está ocupada falla enseguida, sin
	esperar ``timeout`` por cada mensaje.
	"""
	from . import own_windows

	if own_windows.mustDelegate(hwnd):
		try:
			return own_windows.call(sendMessage, hwnd, msg, wParam, lParam, timeout)
		except OSError:
			return None
	result = ULONG_PTR()
	ok = user32.SendMessageTimeoutW(hwnd, msg, wParam, lParam, SMTO_ABORTIFHUNG | SMTO_BLOCK, timeout, ctypes.byref(result))
	if not ok:
		return None
	return int(result.value)


def getWindowStyle(hwnd: int) -> int:
	try:
		return user32.GetWindowLongW(hwnd, GWL_STYLE) & 0xFFFFFFFF
	except Exception:
		return 0


def getWindowText(hwnd: int, maxChars: int = 2_000_000) -> str | None:
	"""Texto completo de una ventana con ``WM_GETTEXT`` (el sistema lo copia entre procesos)."""
	length = sendMessage(hwnd, WM_GETTEXTLENGTH)
	if length is None:
		return None
	length = min(length, maxChars)
	buf = ctypes.create_unicode_buffer(length + 2)
	got = sendMessage(hwnd, WM_GETTEXT, length + 1, ctypes.addressof(buf))
	if got is None:
		return None
	return buf.value


def _processOfWindow(hwnd: int) -> int:
	pid = wintypes.DWORD()
	user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
	return pid.value


class RemoteMemory:
	"""Bloque de memoria dentro de otro proceso (se libera con ``close``)."""

	def __init__(self, hwnd: int, size: int) -> None:
		self.size = size
		self.address = None
		self.handle = None
		self.is32 = False
		pid = _processOfWindow(hwnd)
		if not pid:
			raise OSError("ventana sin proceso")
		self.handle = kernel32.OpenProcess(PROCESS_VM_OPERATION | PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
		if not self.handle:
			raise OSError(ctypes.get_last_error(), "OpenProcess")
		wow = wintypes.BOOL()
		if kernel32.IsWow64Process(self.handle, ctypes.byref(wow)):
			self.is32 = bool(wow.value)
		self.address = kernel32.VirtualAllocEx(self.handle, None, size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
		if not self.address:
			err = ctypes.get_last_error()
			kernel32.CloseHandle(self.handle)
			self.handle = None
			raise OSError(err, "VirtualAllocEx")

	def write(self, data: bytes, offset: int = 0) -> None:
		written = ctypes.c_size_t()
		buf = ctypes.create_string_buffer(data, len(data))
		if not kernel32.WriteProcessMemory(self.handle, self.address + offset, buf, len(data), ctypes.byref(written)):
			raise OSError(ctypes.get_last_error(), "WriteProcessMemory")

	def read(self, size: int, offset: int = 0) -> bytes:
		buf = ctypes.create_string_buffer(size)
		got = ctypes.c_size_t()
		if not kernel32.ReadProcessMemory(self.handle, self.address + offset, buf, size, ctypes.byref(got)):
			raise OSError(ctypes.get_last_error(), "ReadProcessMemory")
		return buf.raw[: got.value]

	def close(self) -> None:
		if self.address and self.handle:
			kernel32.VirtualFreeEx(self.handle, self.address, 0, MEM_RELEASE)
		if self.handle:
			kernel32.CloseHandle(self.handle)
		self.address = None
		self.handle = None

	def __enter__(self) -> "RemoteMemory":
		return self

	def __exit__(self, *exc) -> None:
		self.close()


# ------------------------------------------------------------------ campos de edición
class CHARRANGE(ctypes.Structure):
	_fields_ = [("cpMin", ctypes.c_long), ("cpMax", ctypes.c_long)]


def editGetSelection(hwnd: int) -> tuple[int, int] | None:
	"""Selección ``(inicio, fin)`` de un campo de edición."""
	if isRichEditClass(getClassName(hwnd)):
		try:
			with RemoteMemory(hwnd, ctypes.sizeof(CHARRANGE)) as mem:
				if sendMessage(hwnd, EM_EXGETSEL, 0, mem.address) is None:
					return None
				cr = CHARRANGE.from_buffer_copy(mem.read(ctypes.sizeof(CHARRANGE)))
				return int(cr.cpMin), int(cr.cpMax)
		except OSError:
			pass
	# EM_GETSEL es un mensaje del sistema: Windows copia los punteros entre
	# procesos, así que se pasan variables locales (sin límite de 65535).
	start = wintypes.DWORD()
	end = wintypes.DWORD()
	if sendMessage(hwnd, EM_GETSEL, ctypes.addressof(start), ctypes.addressof(end)) is None:
		return None
	return int(start.value), int(end.value)


def editSetSelection(hwnd: int, start: int, end: int) -> bool:
	ok = sendMessage(hwnd, EM_SETSEL, start, end) is not None
	sendMessage(hwnd, EM_SCROLLCARET)
	return ok


def editLineFromChar(hwnd: int, offset: int) -> int | None:
	return sendMessage(hwnd, EM_LINEFROMCHAR, offset)


def editLineIndex(hwnd: int, line: int) -> int | None:
	res = sendMessage(hwnd, EM_LINEINDEX, line)
	if res is None:
		return None
	# -1 llega como entero sin signo.
	return -1 if res >= 0x7FFFFFFF else res


def editLineLength(hwnd: int, offset: int) -> int | None:
	return sendMessage(hwnd, EM_LINELENGTH, offset)


def editLimitText(hwnd: int) -> int | None:
	return sendMessage(hwnd, EM_GETLIMITTEXT)


# ------------------------------------------------------------------ listas SysListView32
def _lvitemLayout(is32: bool) -> tuple[int, int, int, int]:
	"""Tamaño de LVITEMW y desplazamientos de iSubItem, pszText y cchTextMax."""
	if is32:
		# mask, iItem, iSubItem, state, stateMask (5*4=20), pszText (4), cchTextMax (4), ...
		return 60, 8, 20, 24
	# En 64 bits pszText está alineado a 8: 20 bytes + 4 de relleno.
	return 88, 8, 24, 32


def _hditemLayout(is32: bool) -> tuple[int, int, int]:
	"""Tamaño de HDITEMW y desplazamientos de pszText y cchTextMax."""
	if is32:
		# mask, cxy (8), pszText (4), hbm (4), cchTextMax (4)
		return 48, 8, 16
	# mask, cxy (8), pszText (8, alineado), hbm (8), cchTextMax
	return 72, 8, 24


def listViewItemCount(hwnd: int) -> int:
	return sendMessage(hwnd, LVM_GETITEMCOUNT) or 0


def listViewFocusedItem(hwnd: int) -> int:
	res = sendMessage(hwnd, LVM_GETNEXTITEM, ULONG_PTR(-1 & ((1 << 64) - 1)).value, LVNI_FOCUSED)
	if res is None or res >= 0x7FFFFFFF:
		return -1
	return res


def listViewSelectedItems(hwnd: int, limit: int = 500) -> list[int]:
	out: list[int] = []
	start = (1 << 64) - 1  # -1 sin signo: desde el principio
	for _i in range(limit):
		res = sendMessage(hwnd, LVM_GETNEXTITEM, start, LVNI_SELECTED)
		if res is None or res >= 0x7FFFFFFF:
			break
		out.append(res)
		start = res
	return out


def listViewSelectedCount(hwnd: int) -> int | None:
	"""Número de elementos seleccionados (``None`` si la lista no responde)."""
	res = sendMessage(hwnd, LVM_GETSELECTEDCOUNT)
	if res is None or res >= 0x7FFFFFFF:
		return None
	return int(res)


def listViewIsDetails(hwnd: int) -> bool:
	view = sendMessage(hwnd, LVM_GETVIEW)
	return view == LV_VIEW_DETAILS


def listViewColumnCount(hwnd: int) -> int:
	header = sendMessage(hwnd, LVM_GETHEADER)
	if not header:
		return 0
	return sendMessage(header, HDM_GETITEMCOUNT) or 0


def listViewColumnOrder(hwnd: int, count: int) -> list[int]:
	"""Orden visual de las columnas (índices lógicos)."""
	if count <= 0:
		return []
	try:
		with RemoteMemory(hwnd, 4 * count) as mem:
			if not sendMessage(hwnd, LVM_GETCOLUMNORDERARRAY, count, mem.address):
				return list(range(count))
			raw = mem.read(4 * count)
	except OSError:
		return list(range(count))
	order = [int.from_bytes(raw[i * 4 : i * 4 + 4], "little", signed=True) for i in range(count)]
	if sorted(order) != list(range(count)):
		return list(range(count))
	return order


#: Máximo de hermanos que se recorren para calcular «N de M» en un árbol.
TREE_SIBLING_LIMIT = 3000


def treeViewItemPosition(hwnd: int, accId: int) -> dict[str, int]:
	"""Posición («2 de 31») y nivel de un elemento de un ``SysTreeView32``.

	``accId`` es el identificador de hijo MSAA del elemento; el control lo
	traduce a su ``HTREEITEM`` (``TVM_MAPACCIDTOHTREEITEM``, comctl32 6) y los
	hermanos y antecesores se recorren con ``TVM_GETNEXTITEM``, que solo usa
	identificadores (sin memoria del otro proceso). En las ventanas de
	Tiresias todo se calcula de una vez en el hilo de la interfaz.
	"""
	from . import own_windows

	if not accId:
		return {}
	if own_windows.mustDelegate(hwnd):
		try:
			return own_windows.call(treeViewItemPosition, hwnd, accId)
		except OSError:
			return {}
	item = sendMessage(hwnd, TVM_MAPACCIDTOHTREEITEM, accId, 0)
	if not item:
		return {}
	index = 1
	cur = item
	for _i in range(TREE_SIBLING_LIMIT):
		cur = sendMessage(hwnd, TVM_GETNEXTITEM, TVGN_PREVIOUS, cur)
		if not cur:
			break
		index += 1
	else:
		return {}
	total = index
	cur = item
	for _i in range(TREE_SIBLING_LIMIT):
		cur = sendMessage(hwnd, TVM_GETNEXTITEM, TVGN_NEXT, cur)
		if not cur:
			break
		total += 1
	else:
		return {}
	level = 1
	cur = item
	for _i in range(64):
		cur = sendMessage(hwnd, TVM_GETNEXTITEM, TVGN_PARENT, cur)
		if not cur:
			break
		level += 1
	return {"indexInGroup": index, "similarItemsInGroup": total, "level": level}


def listViewHeaders(hwnd: int) -> list[str]:
	"""Texto de los encabezados de columna (en orden lógico)."""
	header = sendMessage(hwnd, LVM_GETHEADER)
	if not header:
		return []
	count = sendMessage(header, HDM_GETITEMCOUNT) or 0
	out: list[str] = []
	textChars = 260
	try:
		mem = RemoteMemory(header, 128 + textChars * 2)
	except OSError:
		return []
	try:
		size, offText, offMax = _hditemLayout(mem.is32)
		ptrSize = 4 if mem.is32 else 8
		textAddr = mem.address + 128
		for i in range(count):
			item = bytearray(size)
			item[0:4] = HDI_TEXT.to_bytes(4, "little")
			item[offText : offText + ptrSize] = textAddr.to_bytes(ptrSize, "little")
			item[offMax : offMax + 4] = textChars.to_bytes(4, "little")
			mem.write(bytes(item))
			mem.write(b"\0\0", 128)
			if not sendMessage(header, HDM_GETITEMW, i, mem.address):
				out.append("")
				continue
			raw = mem.read(textChars * 2, 128)
			out.append(raw.decode("utf-16-le", "replace").split("\0", 1)[0])
	except OSError:
		log.debug("No se pudieron leer los encabezados", exc_info=True)
	finally:
		mem.close()
	return out


def listViewItemTexts(hwnd: int, item: int, columns: int) -> list[str]:
	"""Texto de cada columna (en orden lógico) del elemento ``item``."""
	out: list[str] = []
	textChars = 1024
	try:
		mem = RemoteMemory(hwnd, 128 + textChars * 2)
	except OSError:
		return out
	try:
		size, offSub, offText, offMax = _lvitemLayout(mem.is32)
		ptrSize = 4 if mem.is32 else 8
		textAddr = mem.address + 128
		for col in range(max(1, columns)):
			lv = bytearray(size)
			lv[offSub : offSub + 4] = col.to_bytes(4, "little", signed=True)
			lv[offText : offText + ptrSize] = textAddr.to_bytes(ptrSize, "little")
			lv[offMax : offMax + 4] = textChars.to_bytes(4, "little")
			mem.write(bytes(lv))
			mem.write(b"\0\0", 128)
			n = sendMessage(hwnd, LVM_GETITEMTEXTW, item, mem.address)
			if n is None:
				out.append("")
				continue
			raw = mem.read(min(textChars, max(n, 0) + 1) * 2, 128)
			out.append(raw.decode("utf-16-le", "replace").split("\0", 1)[0])
	except OSError:
		log.debug("No se pudo leer el elemento %d", item, exc_info=True)
	finally:
		mem.close()
	return out
