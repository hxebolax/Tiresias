"""Gestor de voces neuronales Piper: ver, descargar, usar y borrar voces.

La lista muestra las voces instaladas en ``data/voices`` y las del catálogo
de https://huggingface.co/rhasspy/piper-voices (guardado en la caché). Nada
se descarga sin que el usuario lo pida: el catálogo se actualiza con su
botón y cada voz se descarga con «Descargar e instalar».
"""

from __future__ import annotations

import threading

import wx

from .. import queue_handler
from ..i18n import _
from ..log import getLogger
from ..synth import piper_voices as PV
from . import settings as S

log = getLogger("gui.piper")

FILTER_SPANISH = "*es*"
FILTER_INSTALLED = "*installed*"
FILTER_ALL = "*all*"


class VoiceManagerDialog(wx.Dialog):
	def __init__(self, parent: wx.Window | None) -> None:
		super().__init__(parent, title=_("Gestor de voces neuronales Piper"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self._catalog: list[PV.VoiceEntry] = PV.loadCachedCatalog()
		self._installed: dict[str, PV.InstalledVoice] = {}
		self._rows: list[tuple[str, PV.VoiceEntry | None, PV.InstalledVoice | None]] = []
		self._cancel: threading.Event | None = None
		self._busy = False
		main = wx.BoxSizer(wx.VERTICAL)
		b = S.SettingsBuilder(self, main)
		self.info = b.addStaticText(
			_("Las voces Piper suenan naturales y funcionan sin conexión. Se guardan en la carpeta data\\voices. Ocupan entre 20 y 120 MB cada una.")
		)
		self.filterChoice = b.addChoice(_("&Mostrar:"), [])
		self.voiceList = b.addLabeledControl(
			_("&Voces:"),
			lambda p: wx.ListBox(p, choices=[], style=wx.LB_SINGLE, size=(560, 260)),
			vertical=True,
			proportion=1,
		)
		row = wx.BoxSizer(wx.HORIZONTAL)
		self.downloadBtn = wx.Button(self, label=_("&Descargar e instalar"))
		self.useBtn = wx.Button(self, label=_("&Usar esta voz"))
		self.deleteBtn = wx.Button(self, label=_("&Borrar"))
		self.catalogBtn = wx.Button(self, label=_("Actualizar el &catálogo desde Internet"))
		for btn in (self.downloadBtn, self.useBtn, self.deleteBtn, self.catalogBtn):
			row.Add(btn, 0, wx.RIGHT, 6)
		main.Add(row, 0, wx.BOTTOM, 6)
		self.status = b.addText(_("Estado:"), "", style=wx.TE_READONLY, size=(560, -1))
		self.gauge = b.addLabeledControl(_("Progreso de la descarga:"), lambda p: wx.Gauge(p, range=100, size=(300, -1)))
		self.cancelBtn = b.addButton(_("C&ancelar la descarga"))
		self.cancelBtn.Disable()
		buttons = wx.StdDialogButtonSizer()
		close = wx.Button(self, wx.ID_CLOSE, _("Cerrar"))
		buttons.AddButton(close)
		buttons.Realize()
		main.Add(buttons, 0, wx.ALIGN_RIGHT | wx.TOP, 8)
		outer = wx.BoxSizer(wx.VERTICAL)
		outer.Add(main, 1, wx.EXPAND | wx.ALL, 10)
		self.SetSizer(outer)
		outer.Fit(self)
		self.SetEscapeId(wx.ID_CLOSE)
		close.Bind(wx.EVT_BUTTON, lambda evt: self._close())
		self.Bind(wx.EVT_CLOSE, lambda evt: self._close())
		self.filterChoice.Bind(wx.EVT_CHOICE, lambda evt: self._fillList())
		self.voiceList.Bind(wx.EVT_LISTBOX, lambda evt: self._updateButtons())
		self.downloadBtn.Bind(wx.EVT_BUTTON, self._onDownload)
		self.useBtn.Bind(wx.EVT_BUTTON, self._onUse)
		self.deleteBtn.Bind(wx.EVT_BUTTON, self._onDelete)
		self.catalogBtn.Bind(wx.EVT_BUTTON, self._onCatalog)
		self.cancelBtn.Bind(wx.EVT_BUTTON, self._onCancel)
		self.CentreOnScreen()
		self._reloadInstalled()
		self._fillFilters()
		self._fillList()
		if not self._catalog:
			self._setStatus(_("Pulsa «Actualizar el catálogo desde Internet» para ver las voces que se pueden descargar."))
		self.voiceList.SetFocus()

	# ------------------------------------------------------------ datos
	def _reloadInstalled(self) -> None:
		self._installed = {v.key: v for v in PV.installedVoices()}

	def _fillFilters(self) -> None:
		self._filters: list[tuple[str, str]] = [
			(FILTER_SPANISH, _("Español (España y Latinoamérica)")),
			(FILTER_INSTALLED, _("Voces instaladas")),
			(FILTER_ALL, _("Todos los idiomas")),
		]
		langs: dict[str, str] = {}
		for v in self._catalog:
			langs.setdefault(v.language, v.languageName)
		for code, name in sorted(langs.items(), key=lambda kv: kv[1].lower()):
			self._filters.append((code, name))
		prev = self.filterChoice.GetSelection()
		self.filterChoice.Set([n for _c, n in self._filters])
		self.filterChoice.SetSelection(prev if 0 <= prev < len(self._filters) else 0)

	def _fillList(self) -> None:
		i = self.filterChoice.GetSelection()
		flt = self._filters[i][0] if 0 <= i < len(self._filters) else FILTER_SPANISH
		prevKey = self._selectedKey()
		rows: list[tuple[str, PV.VoiceEntry | None, PV.InstalledVoice | None]] = []
		seen: set[str] = set()
		for entry in self._catalog:
			inst = self._installed.get(entry.key)
			if flt == FILTER_SPANISH and entry.family != "es":
				continue
			if flt == FILTER_INSTALLED and inst is None:
				continue
			if flt not in (FILTER_SPANISH, FILTER_INSTALLED, FILTER_ALL) and entry.language != flt:
				continue
			rows.append((entry.key, entry, inst))
			seen.add(entry.key)
		# Voces instaladas que no están en el catálogo (copiadas a mano o sin catálogo).
		for key, inst in self._installed.items():
			if key in seen:
				continue
			if flt == FILTER_SPANISH and not inst.language.startswith("es"):
				continue
			if flt not in (FILTER_SPANISH, FILTER_INSTALLED, FILTER_ALL) and inst.language != flt:
				continue
			rows.append((key, None, inst))
		self._rows = rows
		self.voiceList.Set([self._label(r) for r in rows] or [_("No hay voces que mostrar")])
		keys = [r[0] for r in rows]
		if rows:
			self.voiceList.SetSelection(keys.index(prevKey) if prevKey in keys else 0)
		self._updateButtons()

	@staticmethod
	def _label(row) -> str:
		key, entry, inst = row
		if entry is not None:
			text = entry.displayName
			if entry.numSpeakers > 1:
				text += ", " + _("{n} hablantes").format(n=entry.numSpeakers)
			text += ", " + PV.formatSize(entry.size)
		else:
			text = inst.displayName
		if inst is not None:
			text += " — " + _("instalada")
		return text

	def _selected(self):
		i = self.voiceList.GetSelection()
		return self._rows[i] if 0 <= i < len(self._rows) else None

	def _selectedKey(self) -> str | None:
		row = self._selected() if hasattr(self, "_rows") else None
		return row[0] if row else None

	def _updateButtons(self) -> None:
		row = self._selected()
		installed = bool(row and row[2] is not None)
		self.downloadBtn.Enable(bool(row and row[1] is not None) and not self._busy)
		self.downloadBtn.SetLabel(_("Volver a &descargar") if installed else _("&Descargar e instalar"))
		self.useBtn.Enable(installed and not self._busy)
		self.deleteBtn.Enable(installed and not self._busy)
		self.catalogBtn.Enable(not self._busy)

	def _setStatus(self, text: str, speak: bool = False) -> None:
		if S.isAlive(self):
			self.status.SetValue(text)
			if speak:
				S.speakMessageOnCore(text)

	# ------------------------------------------------------------ catálogo
	def _onCatalog(self, evt) -> None:
		self._busy = True
		self._updateButtons()
		self._setStatus(_("Descargando el catálogo de voces..."), speak=True)

		def work() -> None:
			try:
				catalog = PV.fetchCatalog()
				error = None
			except Exception as e:
				log.warning("No se pudo descargar el catálogo de voces", exc_info=True)
				catalog, error = None, e
			wx.CallAfter(self._onCatalogDone, catalog, error)

		threading.Thread(target=work, name="PiperCatalog", daemon=True).start()

	def _onCatalogDone(self, catalog, error) -> None:
		if not S.isAlive(self):
			return
		self._busy = False
		if catalog is None:
			self._setStatus(_("No se pudo descargar el catálogo: {error}").format(error=error), speak=True)
		else:
			self._catalog = catalog
			self._fillFilters()
			self._fillList()
			self._setStatus(_("Catálogo actualizado: {n} voces disponibles.").format(n=len(catalog)), speak=True)
		self._updateButtons()

	# ------------------------------------------------------------ descarga
	def _onDownload(self, evt) -> None:
		row = self._selected()
		if not row or row[1] is None:
			return
		entry = row[1]
		if not S.askYesNo(
			_("¿Descargar la voz {name}? Ocupa {size}.").format(name=entry.displayName, size=PV.formatSize(entry.size)),
			_("Descargar voz"),
			self,
		):
			return
		self._busy = True
		self._cancel = threading.Event()
		self.cancelBtn.Enable()
		self.gauge.SetValue(0)
		self._updateButtons()
		self._setStatus(_("Descargando {name}...").format(name=entry.displayName), speak=True)
		cancel = self._cancel
		lastPct = [-1]

		def progress(done: int, total: int) -> None:
			pct = int(done * 100 / total) if total else 0
			if pct != lastPct[0]:
				lastPct[0] = pct
				wx.CallAfter(self._onProgress, pct)

		def work() -> None:
			try:
				PV.downloadVoice(entry, progress, cancel)
				error = None
			except PV.DownloadCancelled:
				error = "cancel"
			except Exception as e:
				log.warning("Error descargando la voz %s", entry.key, exc_info=True)
				error = e
			wx.CallAfter(self._onDownloadDone, entry, error)

		threading.Thread(target=work, name="PiperDownload", daemon=True).start()

	def _onProgress(self, pct: int) -> None:
		if S.isAlive(self):
			self.gauge.SetValue(max(0, min(100, pct)))
			if pct % 25 == 0 and 0 < pct < 100:
				self._setStatus(_("Descargado el {pct} %").format(pct=pct), speak=True)

	def _onDownloadDone(self, entry: PV.VoiceEntry, error) -> None:
		if not S.isAlive(self):
			return
		self._busy = False
		self._cancel = None
		self.cancelBtn.Disable()
		if error == "cancel":
			self.gauge.SetValue(0)
			self._setStatus(_("Descarga cancelada."), speak=True)
		elif error is not None:
			self.gauge.SetValue(0)
			self._setStatus(_("No se pudo descargar la voz: {error}").format(error=error), speak=True)
		else:
			self.gauge.SetValue(100)
			self._setStatus(_("Voz {name} instalada. Pulsa «Usar esta voz» para escucharla.").format(name=entry.displayName), speak=True)
			self._reloadInstalled()
			self._fillList()
			queue_handler.queueFunction(_refreshPiperSynth)
		self._updateButtons()

	def _onCancel(self, evt) -> None:
		if self._cancel is not None:
			self._cancel.set()

	# ------------------------------------------------------------ usar y borrar
	def _onUse(self, evt) -> None:
		row = self._selected()
		if not row or row[2] is None:
			return
		key = row[0]
		self._setStatus(_("Cargando la voz..."))
		S.runOnCore(_usePiperVoice, key, callback=self._onUsed)

	def _onUsed(self, ok) -> None:
		if not S.isAlive(self):
			return
		if ok:
			self._setStatus(_("Tiresias usa ahora esta voz."))
		else:
			self._setStatus(_("No se pudo cargar la voz."), speak=True)
		S._onSynthChanged()

	def _onDelete(self, evt) -> None:
		row = self._selected()
		if not row or row[2] is None:
			return
		inst = row[2]
		if not S.askYesNo(_("¿Borrar la voz {name}?").format(name=inst.displayName), _("Borrar voz"), self):
			return
		key = row[0]
		S.runOnCore(_deletePiperVoice, key, callback=self._onDeleted)

	def _onDeleted(self, ok) -> None:
		if not S.isAlive(self):
			return
		self._reloadInstalled()
		self._fillList()
		self._setStatus(_("Voz borrada.") if ok else _("No se pudo borrar la voz."), speak=True)
		S._onSynthChanged()

	def _close(self) -> None:
		global _dialog
		if self._cancel is not None:
			self._cancel.set()
		if _dialog is self:
			_dialog = None
		self.Hide()
		self.Destroy()


# ---------------------------------------------------------------- núcleo
def _refreshPiperSynth() -> None:
	from .. import synth

	cur = synth.getSynth()
	if cur is not None and cur.name == "piper":
		cur.refreshVoices()


def _usePiperVoice(key: str) -> bool:
	from .. import synth
	from ..config import conf

	cur = synth.getSynth()
	if cur is None or cur.name != "piper":
		if not synth.setSynth("piper", isFallback=True):
			return False
		cur = synth.getSynth()
		if cur is None or cur.name != "piper":
			return False
		conf["speech"]["synth"] = "piper"
	else:
		cur.refreshVoices()
	synth.changeSetting("voice", key)
	from .. import speech

	speech.speakMessage(_("Voz {name}").format(name=cur.availableVoices[key].displayName if key in cur.availableVoices else key))
	return True


def _deletePiperVoice(key: str) -> bool:
	from .. import synth

	cur = synth.getSynth()
	if cur is not None and cur.name == "piper" and cur.getSetting("voice") == key:
		# La voz está en uso: se libera antes de borrarla.
		others = [v.key for v in PV.installedVoices() if v.key != key]
		if others:
			synth.changeSetting("voice", others[0])
			cur.cancel()
			cur._voice = None
		else:
			synth.setSynth("auto")
	ok = PV.deleteVoice(key)
	cur = synth.getSynth()
	if cur is not None and cur.name == "piper":
		cur.refreshVoices()
	return ok


_dialog: VoiceManagerDialog | None = None


def showVoiceManager() -> None:
	"""Abre (o trae al frente) el gestor de voces Piper (hilo de la interfaz)."""
	global _dialog
	if _dialog is None or not S.isAlive(_dialog):
		_dialog = VoiceManagerDialog(S.parentWindow())
	S.presentDialog(_dialog)
