"""Microsoft Outlook (clásico).

- Al abrir un mensaje se puede leer solo el cuerpo (NVDA #11161), no leer
  nada (NVDA #15310) o dejar el comportamiento normal: opción «Al abrir un
  mensaje» del panel Aplicaciones.
- En una ventana de mensaje, Alt+1 a Alt+6 leen las cabeceras (De, Fecha,
  Para, CC, Asunto, Adjuntos) y, al redactar, los campos (Para, CC, CCO,
  Asunto, Adjuntos). Dos pulsaciones muestran el campo en una ventana.
- Tiresias+Alt+Mayúsculas+H lee los detalles del elemento seleccionado: mensaje
  (remitente, asunto, fecha, tamaño, adjuntos, importancia, marca,
  categorías) o, en el calendario, la franja seleccionada y sus citas.
- Tiresias+Control+Mayúsculas+A muestra los adjuntos del mensaje abierto o
  seleccionado (nombre y tamaño) para abrirlos o guardarlos (foros 3.9).
- El cuerpo de los mensajes usa todo lo del módulo de Word (comentarios,
  formato, tablas...), porque Outlook edita el correo con Word.
"""

from __future__ import annotations

import datetime

from .. import api, speech, winapi
from ..baseobject import script
from ..config import conf
from ..i18n import _
from ..log import getLogger
from . import AppModule as BaseAppModule
from . import _chart, _office
from .winword import isWordDocument, useWordDocument

log = getLogger("outlook")

CAT = _("Microsoft Outlook")

#: Clase de las ventanas principales de Outlook (explorador e inspectores).
OUTLOOK_WINDOW_CLASS = "rctrl_renwnd32"
olInspector = 35
olMail = 43
olAppointment = 26
olMeetingRequest = 53
olFolderCalendar = 9

IMPORTANCE = {0: _("importancia baja"), 2: _("importancia alta")}


def _fail(error: BaseException) -> None:
	speech.speakMessage(_office.busyMessage(error))


def _outlook():
	return _office.activeObject("Outlook.Application")


def _fmtDate(value) -> str:
	if isinstance(value, datetime.datetime):
		if value.year >= 4000:
			return ""
		return value.strftime("%d/%m/%Y %H:%M")
	return str(value or "")


# ================================================================ modelo de objetos
def om_inspectorFields() -> dict | None:
	"""Campos del elemento de la ventana de mensaje activa (``None`` si no lo es)."""
	app = _outlook()
	win = app.ActiveWindow()
	if win is None or int(win.Class) != olInspector:
		return None
	item = win.CurrentItem
	out: dict = {"class": int(item.Class), "sent": True, "fields": {}}
	try:
		out["sent"] = bool(item.Sent)
	except Exception:
		pass
	attachments = []
	try:
		att = item.Attachments
		for i in range(1, int(att.Count) + 1):
			a = att.Item(i)
			size = int(getattr(a, "Size", 0) or 0)
			attachments.append(f"{a.FileName} ({max(1, size // 1024)} KB)" if size else a.FileName)
	except Exception:
		pass
	get = lambda name: str(getattr(item, name, "") or "")  # noqa: E731
	f = out["fields"]
	if out["class"] == olMail:
		f["from"] = get("SenderName")
		try:
			f["date"] = _fmtDate(item.ReceivedTime if out["sent"] else item.CreationTime)
		except Exception:
			f["date"] = ""
		f["to"] = get("To")
		f["cc"] = get("CC")
		f["bcc"] = get("BCC")
		f["subject"] = get("Subject")
	elif out["class"] in (olAppointment, olMeetingRequest):
		f["subject"] = get("Subject")
		f["location"] = get("Location")
		try:
			f["start"] = _fmtDate(item.Start)
			f["end"] = _fmtDate(item.End)
		except Exception:
			pass
		f["to"] = get("RequiredAttendees")
		f["cc"] = get("OptionalAttendees")
		f["organizer"] = get("Organizer")
	else:
		f["subject"] = get("Subject")
	f["attachments"] = "; ".join(attachments)
	return out


#: Qué campo lee cada Alt+número: (mensaje recibido, mensaje en redacción).
FIELD_KEYS = {
	1: ("from", "to"),
	2: ("date", "cc"),
	3: ("to", "bcc"),
	4: ("cc", "subject"),
	5: ("subject", "attachments"),
	6: ("attachments", None),
}
#: Para citas y convocatorias.
APPOINTMENT_KEYS = {1: "subject", 2: "location", 3: "start", 4: "end", 5: "to", 6: "attachments"}

FIELD_LABELS = {
	"from": _("De"),
	"date": _("Fecha"),
	"to": _("Para"),
	"cc": _("CC"),
	"bcc": _("CCO"),
	"subject": _("Asunto"),
	"attachments": _("Adjuntos"),
	"location": _("Ubicación"),
	"start": _("Comienzo"),
	"end": _("Fin"),
	"organizer": _("Organizador"),
}


def fieldFor(data: dict, number: int) -> tuple[str, str] | None:
	"""(etiqueta, valor) del campo ``number`` para los datos de :func:`om_inspectorFields`."""
	if data["class"] in (olAppointment, olMeetingRequest):
		key = APPOINTMENT_KEYS.get(number)
	else:
		pair = FIELD_KEYS.get(number)
		key = (pair[0] if data.get("sent", True) else pair[1]) if pair else None
	if not key:
		return None
	return FIELD_LABELS[key], data["fields"].get(key, "")


def om_selectionDetails() -> dict:
	"""Detalles de lo seleccionado en el explorador (mensajes o calendario)."""
	app = _outlook()
	exp = app.ActiveExplorer()
	out: dict = {"items": [], "calendar": False}
	folder = exp.CurrentFolder
	try:
		out["calendar"] = int(folder.DefaultItemType) == 1  # olAppointmentItem
	except Exception:
		pass
	if out["calendar"]:
		try:
			view = exp.CurrentView
			out["slotStart"] = _fmtDate(view.SelectedStartTime)
			out["slotEnd"] = _fmtDate(view.SelectedEndTime)
		except Exception:
			pass
	sel = exp.Selection
	for i in range(1, min(int(sel.Count), 20) + 1):
		it = sel.Item(i)
		d: dict = {"class": int(it.Class), "subject": str(getattr(it, "Subject", "") or "")}
		if d["class"] == olMail:
			d["from"] = str(getattr(it, "SenderName", "") or "")
			try:
				d["date"] = _fmtDate(it.ReceivedTime)
			except Exception:
				pass
			try:
				d["size"] = int(it.Size)
				d["attachments"] = int(it.Attachments.Count)
				d["importance"] = int(it.Importance)
				d["unread"] = bool(it.UnRead)
				d["flagged"] = int(getattr(it, "FlagStatus", 0) or 0) == 2
				d["categories"] = str(it.Categories or "")
			except Exception:
				pass
		elif d["class"] in (olAppointment, olMeetingRequest):
			try:
				d["start"] = _fmtDate(it.Start)
				d["end"] = _fmtDate(it.End)
				d["location"] = str(it.Location or "")
			except Exception:
				pass
		out["items"].append(d)
	return out


def detailsText(d: dict) -> str:
	parts: list[str] = []
	if d.get("calendar") and d.get("slotStart"):
		parts.append(_("Franja de {start} a {end}").format(start=d["slotStart"], end=d.get("slotEnd", "")))
	items = d.get("items") or []
	if not items:
		if not parts:
			parts.append(_("No hay nada seleccionado"))
		return ". ".join(parts)
	if len(items) > 1:
		parts.append(_("{n} elementos seleccionados").format(n=len(items)))
	for it in items:
		p: list[str] = []
		if it["class"] == olMail:
			if it.get("unread"):
				p.append(_("no leído"))
			if it.get("from"):
				p.append(_("de {name}").format(name=it["from"]))
			p.append(it.get("subject") or _("sin asunto"))
			if it.get("date"):
				p.append(it["date"])
			if it.get("attachments"):
				p.append(_("{n} adjuntos").format(n=it["attachments"]) if it["attachments"] != 1 else _("1 adjunto"))
			if it.get("importance") in IMPORTANCE:
				p.append(IMPORTANCE[it["importance"]])
			if it.get("flagged"):
				p.append(_("marcado para seguimiento"))
			if it.get("categories"):
				p.append(_("categorías {c}").format(c=it["categories"]))
			if it.get("size"):
				p.append(_("{n} KB").format(n=max(1, it["size"] // 1024)))
		else:
			p.append(it.get("subject") or _("sin asunto"))
			if it.get("start"):
				p.append(_("de {start} a {end}").format(start=it["start"], end=it.get("end", "")))
			if it.get("location"):
				p.append(it["location"])
		parts.append(", ".join(p))
	return ". ".join(parts)


# ================================================================ adjuntos (foros 3.9)
#: Extensiones que Outlook bloquea por peligrosas: no se abren, solo se guardan.
BLOCKED_EXTENSIONS = {
	".ade", ".adp", ".app", ".application", ".appref-ms", ".bat", ".cer", ".chm", ".cmd", ".com", ".cpl", ".crt", ".der",
	".exe", ".gadget", ".hlp", ".hta", ".inf", ".ins", ".isp", ".its", ".js", ".jse", ".lnk", ".mde", ".msc", ".msi", ".msp",
	".mst", ".pif", ".ps1", ".ps1xml", ".ps2", ".psc1", ".reg", ".scf", ".scr", ".sct", ".shb", ".shs", ".url", ".vb", ".vbe",
	".vbs", ".ws", ".wsc", ".wsf", ".wsh", ".xbap", ".xll",
	# Imágenes de disco (al montarlas su contenido no lleva la marca de Internet),
	# Java y paquetes de aplicaciones.
	".iso", ".img", ".vhd", ".vhdx", ".jar", ".msix", ".msixbundle", ".appx", ".appxbundle", ".library-ms", ".settingcontent-ms",
}
#: Propiedad MAPI de los adjuntos ocultos (imágenes incrustadas en el cuerpo).
_PR_ATTACHMENT_HIDDEN = "http://schemas.microsoft.com/mapi/proptag/0x7FFE000B"


def _currentItem(app):
	"""(elemento, origen): el de la ventana de mensaje activa o el primero seleccionado."""
	win = app.ActiveWindow()
	if win is not None and int(win.Class) == olInspector:
		return win.CurrentItem, "inspector"
	exp = app.ActiveExplorer()
	if exp is not None:
		sel = exp.Selection
		if int(sel.Count) >= 1:
			return sel.Item(1), "explorer"
	return None, ""


def om_attachments() -> dict:
	"""Adjuntos del mensaje abierto o seleccionado: ``{"subject", "entryId", "items"}``."""
	app = _outlook()
	item, where = _currentItem(app)
	out: dict = {"subject": "", "entryId": "", "where": where, "items": []}
	if item is None:
		return out
	out["subject"] = str(getattr(item, "Subject", "") or "")
	try:
		out["entryId"] = str(item.EntryID or "")
	except Exception:
		pass
	att = item.Attachments
	for i in range(1, int(att.Count) + 1):
		a = att.Item(i)
		try:
			if a.PropertyAccessor.GetProperty(_PR_ATTACHMENT_HIDDEN):
				continue
		except Exception:
			pass
		name = str(getattr(a, "FileName", "") or "") or str(getattr(a, "DisplayName", "") or "")
		size = 0
		try:
			size = int(a.Size or 0)
		except Exception:
			pass
		kind = 1
		try:
			kind = int(a.Type)
		except Exception:
			pass
		out["items"].append({"index": i, "name": name, "size": size, "type": kind})
	return out


def _resolveItem(app, entryId: str):
	if entryId:
		try:
			return app.Session.GetItemFromID(entryId)
		except Exception:
			pass
	return _currentItem(app)[0]


def om_saveAttachment(entryId: str, index: int, name: str, path: str) -> str:
	"""Guarda el adjunto ``index`` (comprobando su nombre) en ``path``."""
	app = _outlook()
	item = _resolveItem(app, entryId)
	if item is None:
		raise _office.OfficeUnavailable("sin mensaje")
	att = item.Attachments
	target = None
	if 1 <= index <= int(att.Count):
		a = att.Item(index)
		if (str(getattr(a, "FileName", "") or "") or str(getattr(a, "DisplayName", "") or "")) == name:
			target = a
	if target is None:
		for i in range(1, int(att.Count) + 1):
			a = att.Item(i)
			if str(getattr(a, "FileName", "") or "") == name:
				target = a
				break
	if target is None:
		raise _office.OfficeUnavailable("adjunto no encontrado")
	target.SaveAsFile(path)
	markFromInternet(path)
	return path


def sizeText(size: int) -> str:
	if size <= 0:
		return ""
	if size < 1024:
		return _("{n} bytes").format(n=size)
	if size < 1024 * 1024:
		return _("{n} KB").format(n=max(1, size // 1024))
	return _("{n} MB").format(n=f"{size / (1024 * 1024):.1f}".replace(".", ","))


def attachmentLabel(a: dict) -> str:
	parts = [a.get("name") or _("sin nombre")]
	size = sizeText(int(a.get("size") or 0))
	if size:
		parts.append(size)
	if a.get("type") == 5:
		parts.append(_("elemento de Outlook"))
	elif a.get("type") == 4:
		parts.append(_("enlace"))
	return ", ".join(parts)


def isBlocked(name: str) -> bool:
	"""``True`` si el adjunto no debe abrirse. Se mira el nombre con el que se
	guardará (:func:`safeFileName`): Windows quita los puntos y espacios finales,
	así que «factura.exe.» acabaría siendo «factura.exe»."""
	import os

	for candidate in (name or "", safeFileName(name)):
		if os.path.splitext(candidate.rstrip(" ."))[1].lower() in BLOCKED_EXTENSIONS:
			return True
	return False


def markFromInternet(path: str) -> bool:
	"""Marca de Internet (``Zone.Identifier``, zona 3) en un adjunto guardado.

	Así Windows y Office lo tratan como lo que es, un archivo recibido por
	correo: aviso de SmartScreen, Vista protegida y macros bloqueadas.
	"""
	try:
		with open(path + ":Zone.Identifier", "w", encoding="ascii") as f:
			f.write("[ZoneTransfer]\r\nZoneId=3\r\n")
		return True
	except OSError:
		return False


def safeFileName(name: str) -> str:
	"""Nombre de archivo válido en Windows a partir del nombre del adjunto."""
	bad = '<>:"/\\|?*'
	cleaned = "".join("_" if ch in bad or ord(ch) < 32 else ch for ch in (name or "")).strip(" .")
	return cleaned or _("adjunto")


# ================================================================ módulo
def _rootClass(obj) -> str:
	try:
		root = winapi.getAncestor(obj.windowHandle, winapi.GA_ROOT)
		return winapi.getClassName(root)
	except Exception:
		return ""


# El cuerpo de los mensajes es un documento de Word, con su orden de gráficos
# (Tiresias+Alt+G), que necesita la navegación por gráficos del módulo.
class AppModule(_chart.ChartNavigationMixin, BaseAppModule):
	scriptCategory = CAT

	def __init__(self, processID: int, appName: str | None = None) -> None:
		super().__init__(processID, appName)
		#: Ventanas de mensaje cuyo cuerpo ya recibió el foco.
		self._seenInspectors: set[int] = set()
		self._explorerCache: dict[int, bool] = {}

	def chooseObjectClass(self, obj, clsList: list[type]) -> None:
		if isWordDocument(obj):
			useWordDocument(clsList)

	# ------------------------------------------------------------ abrir mensajes
	def _isMessageBody(self, obj) -> int:
		"""Ventana del mensaje si ``obj`` es el cuerpo de una ventana de mensaje."""
		if not isWordDocument(obj):
			return 0
		try:
			root = winapi.getAncestor(obj.windowHandle, winapi.GA_ROOT)
		except Exception:
			return 0
		if winapi.getClassName(root) != OUTLOOK_WINDOW_CLASS:
			return 0
		# El explorador (ventana principal) también usa esta clase; su panel de
		# lectura no es una ventana de mensaje. Se distingue por la lista de
		# mensajes (``SUPERGRID``) o el panel de carpetas que solo él tiene.
		isExplorer = self._explorerCache.get(root)
		if isExplorer is None:
			isExplorer = bool(_office.findChildWindow(root, "SUPERGRID") or _office.findChildWindow(root, "NetUINavPaneHost"))
			self._explorerCache[root] = isExplorer
		return 0 if isExplorer else root

	def event_gainFocus(self, obj, nextHandler) -> None:
		mode = conf["mail"]["openMessageReading"]
		root = self._isMessageBody(obj) if mode != "full" else 0
		if not root or root in self._seenInspectors:
			nextHandler()
			return
		self._seenInspectors.add(root)
		if len(self._seenInspectors) > 200:
			self._seenInspectors = {root}
		try:
			readOnly = not obj.isEditable
		except Exception:
			readOnly = True
		if not readOnly:
			# Redacción: el comportamiento normal (se lee el campo).
			nextHandler()
			return
		if mode == "none":
			# Solo se dijo el título de la ventana (el asunto).
			return
		# «body»: se lee el cuerpo desde el principio, sin el nombre del documento.
		from ..speech import sayall

		speech.cancelSpeech()
		sayall.readText(sayall.CURSOR_CARET)

	# ------------------------------------------------------------ campos con Alt+número
	def _readField(self, gesture, number: int) -> None:
		focus = api.getFocusObject()
		if focus is None or _rootClass(focus) != OUTLOOK_WINDOW_CLASS:
			gesture.send()
			return
		from ..input import core as inputCore

		show = inputCore.getLastScriptRepeatCount() == 1
		# Hasta saber si la tecla es de Outlook, las teclas siguientes esperan
		# (y luego se reenvían en orden detrás de esta).
		release = inputCore.manager.deferInterceptedSend()

		def done(data) -> None:
			if data is None:
				# No es una ventana de mensaje: la tecla es de Outlook.
				gesture.send()
				return
			field = fieldFor(data, number)
			if field is None:
				gesture.send()
				return
			label, value = field
			if show and value:
				from .. import gui

				gui.showBrowseableMessage(value.replace("; ", "\n"), label)
				return
			speech.cancelSpeech()
			speech.speakText(f"{label}: {value}" if value else _("{label} vacío").format(label=label))

		def finish(data) -> None:
			try:
				done(data)
			finally:
				release()

		def failed(error) -> None:
			gesture.send()
			release()

		_office.callAsync(om_inspectorFields, callback=finish, onError=failed, timeout=1.0)

	@script(description=_("En una ventana de mensaje: lee De (al redactar, Para). Dos veces: lo muestra"), category=CAT, gesture="kb:alt+1")
	def script_field1(self, gesture) -> None:
		self._readField(gesture, 1)

	@script(description=_("En una ventana de mensaje: lee la fecha (al redactar, CC)"), category=CAT, gesture="kb:alt+2")
	def script_field2(self, gesture) -> None:
		self._readField(gesture, 2)

	@script(description=_("En una ventana de mensaje: lee Para (al redactar, CCO)"), category=CAT, gesture="kb:alt+3")
	def script_field3(self, gesture) -> None:
		self._readField(gesture, 3)

	@script(description=_("En una ventana de mensaje: lee CC (al redactar, el asunto)"), category=CAT, gesture="kb:alt+4")
	def script_field4(self, gesture) -> None:
		self._readField(gesture, 4)

	@script(description=_("En una ventana de mensaje: lee el asunto (al redactar, los adjuntos)"), category=CAT, gesture="kb:alt+5")
	def script_field5(self, gesture) -> None:
		self._readField(gesture, 5)

	@script(description=_("En una ventana de mensaje recibido: lee los adjuntos"), category=CAT, gesture="kb:alt+6")
	def script_field6(self, gesture) -> None:
		self._readField(gesture, 6)

	# Pueden reenviar su tecla a Outlook: las teclas siguientes no se adelantan.
	script_field1.interceptsGesture = script_field2.interceptsGesture = script_field3.interceptsGesture = True  # type: ignore[attr-defined]
	script_field4.interceptsGesture = script_field5.interceptsGesture = script_field6.interceptsGesture = True  # type: ignore[attr-defined]

	@script(description=_("Lee los detalles del mensaje seleccionado o, en el calendario, la franja y las citas seleccionadas"), category=CAT, gesture="kb:tiresias+alt+shift+h", speakOnDemand=True)
	def script_selectionDetails(self, gesture) -> None:
		_office.callAsync(om_selectionDetails, callback=lambda d: speech.speakText(detailsText(d)), onError=_fail, timeout=3)

	# ------------------------------------------------------------ adjuntos (foros 3.9)
	@script(description=_("Lista de adjuntos del mensaje abierto o seleccionado, para abrirlos o guardarlos"), category=CAT, gesture="kb:tiresias+control+shift+a")
	def script_attachmentsList(self, gesture) -> None:
		def done(data: dict) -> None:
			items = data.get("items") or []
			if not data.get("where"):
				speech.speakMessage(_("No hay ningún mensaje abierto ni seleccionado"))
				return
			if not items:
				speech.speakMessage(_("El mensaje no tiene adjuntos"))
				return
			showAttachmentsDialog(data)

		_office.callAsync(om_attachments, callback=done, onError=_fail, timeout=4)


def _attachmentsFolder() -> str:
	import os
	import tempfile

	folder = tempfile.mkdtemp(prefix="adjunto-", dir=_tempRoot())
	os.makedirs(folder, exist_ok=True)
	return folder


def _tempRoot() -> str:
	import os

	from .. import paths

	# Dentro de data\temp: todo lo que genera Tiresias está en data.
	root = os.path.join(paths.tempDir(), "adjuntos")
	os.makedirs(root, exist_ok=True)
	return root


def showAttachmentsDialog(data: dict) -> None:
	"""Diálogo con los adjuntos: abrir, guardar uno o guardarlos todos (en el hilo de la interfaz)."""
	import os

	from .. import queue_handler
	from ..gui import app_dialogs

	entryId = data.get("entryId", "")
	items = [(attachmentLabel(a), a) for a in data.get("items") or []]

	def save(a: dict, path: str, announce: bool = True) -> None:
		def ok(p: str) -> None:
			if announce:
				speech.speakMessage(_("Guardado {name}").format(name=os.path.basename(p)))

		_office.callAsync(om_saveAttachment, entryId, a["index"], a["name"], path, callback=ok, onError=_fail, timeout=30)

	def openAttachment(a: dict) -> None:
		if isBlocked(a["name"]):
			speech.speakMessage(_("Por seguridad no se abre {name}; guárdalo y revísalo antes").format(name=a["name"]))
			return

		def onCore() -> None:
			path = os.path.join(_attachmentsFolder(), safeFileName(a["name"]))

			def ok(p: str) -> None:
				speech.speakMessage(_("Abriendo {name}").format(name=a["name"]))
				try:
					os.startfile(p)  # noqa: S606 - abre con la aplicación asociada, como Outlook
				except OSError:
					speech.speakMessage(_("No hay ninguna aplicación para abrir {name}").format(name=a["name"]))

			_office.callAsync(om_saveAttachment, entryId, a["index"], a["name"], path, callback=ok, onError=_fail, timeout=30)

		queue_handler.queueFunction(onCore)

	def saveOne(a: dict) -> None:
		import wx

		with wx.FileDialog(None, _("Guardar el adjunto"), defaultFile=safeFileName(a["name"]), style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dlg:
			if dlg.ShowModal() != wx.ID_OK:
				return
			path = dlg.GetPath()
		queue_handler.queueFunction(save, a, path)

	def saveAll(_a: dict) -> None:
		import wx

		with wx.DirDialog(None, _("Carpeta donde guardar todos los adjuntos")) as dlg:
			if dlg.ShowModal() != wx.ID_OK:
				return
			folder = dlg.GetPath()

		def onCore() -> None:
			used: set[str] = set()
			for _label, a in items:
				name = safeFileName(a["name"])
				base, ext = os.path.splitext(name)
				n = 2
				while name.lower() in used:
					name = f"{base} ({n}){ext}"
					n += 1
				used.add(name.lower())
				save(a, os.path.join(folder, name), announce=False)
			speech.speakMessage(_("Guardando {n} adjuntos en {folder}").format(n=len(items), folder=folder))

		queue_handler.queueFunction(onCore)

	title = _("Adjuntos de {subject}").format(subject=data.get("subject") or _("sin asunto"))
	app_dialogs.showItemList(
		"outlookAttachments",
		title,
		[(_("Adjuntos"), lambda: list(items))],
		[
			app_dialogs.Action(_("&Abrir"), openAttachment, default=True),
			app_dialogs.Action(_("&Guardar como..."), saveOne),
			app_dialogs.Action(_("Guardar &todos..."), saveAll),
		],
	)
