"""Motor común de «Asistentes de IA accesibles».

Claude, Codex (la aplicación ChatGPT) y el panel de agente de Antigravity son
páginas web dentro de Electron. Sus conversaciones se leen bien en modo
exploración, pero para un usuario ciego falta lo que da un chat accesible:
saber cuándo termina el asistente, oír la última respuesta sin perder el sitio
y pasar de un mensaje a otro.

Este módulo reúne:

- :class:`Nodo` y las funciones puras que sacan los mensajes de un árbol
  (sin UIA, para poder probarlas);
- :class:`AsistenteAppModule`, el módulo de aplicación base, con las órdenes y
  la vigilancia del fin de cada turno. Cada aplicación aporta solo cómo
  encontrar su conversación (:meth:`AsistenteAppModule.buscarConversacion`), el
  cuadro de escribir y cómo saber si está trabajando.

Nada de esto escribe en la aplicación ni pulsa botones: solo lee y mueve el
foco al cuadro de escribir cuando se pide.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterator

from tiresias import api, queue_handler, speech
from tiresias.a11y import uia_client as uc
from tiresias.appmodules import AppModule as BaseAppModule
from tiresias.audio import tones
from tiresias.baseobject import script
from tiresias.config import conf
from tiresias.i18n import _
from tiresias.input import core as inputCore
from tiresias.log import getLogger
from tiresias.objects.uia import UIAObject

from . import ia_opciones

log = getLogger("asistentesIA")

CAT = _("Asistentes de IA")

USUARIO = "usuario"
ASISTENTE = "asistente"

#: Intervalos de la vigilancia (ms): con la aplicación delante y detrás.
INTERVALO_DELANTE = 1200
INTERVALO_DETRAS = 2500
#: Comprobaciones seguidas sin trabajar que hacen falta para dar el turno por
#: terminado: entre dos pasos de un agente el indicador se apaga un momento.
PASADAS_PARA_TERMINAR = 2
#: Largo máximo de lo que se dice de un mensaje al pasar por él.
LARGO_VOZ = 4000

#: Botón de detener del cuadro de escribir (cualquier idioma de la interfaz).
RE_DETENER = re.compile(r"^(detener|parar|interrumpir|cancelar|stop|cancel|interrupt)\b", re.I)
RE_HORA = re.compile(r"^\d{1,2}:\d{2}(\s*[ap]\.?\s?m\.?)?$", re.I)
RE_CONTADOR = re.compile(r"^[+-]\d+$")
#: Aviso fijo bajo el cuadro de escribir de Antigravity: no es un mensaje.
RE_AVISO_IA = re.compile(r"^(ai may make mistakes|la ia puede cometer errores)", re.I)
#: Texto que termina una idea: lo siguiente, si es otro bloque, va en otra línea.
RE_FIN_IDEA = re.compile(r"[.:!?…]\s*$")


@dataclass
class Nodo:
	"""Elemento de la conversación, sin UIA."""

	name: str = ""
	ct: int = 0
	aria: str = ""
	cls: str = ""
	aid: str = ""
	ariaProps: str = ""
	children: list["Nodo"] = field(default_factory=list)
	el: object = None

	def walk(self) -> Iterator["Nodo"]:
		yield self
		for c in self.children:
			yield from c.walk()

	@property
	def oculto(self) -> bool:
		"""Texto solo para lectores de pantalla: rótulos que no son del mensaje."""
		return "sr-only" in self.cls


@dataclass
class Mensaje:
	autor: str
	texto: str
	enCurso: bool = False


def nodoDesde(el) -> Nodo:
	"""Convierte un elemento con su subárbol en caché en :class:`Nodo`."""

	def get(prop, default=""):
		try:
			val = el.GetCachedPropertyValue(prop)
		except Exception:
			return default
		return default if val is None or uc.isNotSupported(val) else val

	n = Nodo(str(get(uc.P_NAME)), int(get(uc.P_CONTROLTYPE, 0) or 0), str(get(uc.P_ARIAROLE)), str(get(uc.P_CLASSNAME)), str(get(uc.P_AUTOMATIONID)), str(get(uc.P_ARIAPROPERTIES)), [], el)
	try:
		arr = el.GetCachedChildren()
		for i in range(arr.Length if arr else 0):
			n.children.append(nodoDesde(arr.GetElement(i)))
	except Exception:
		pass
	return n


# ---------------------------------------------------------------------- texto
def _esBotonEnLinea(n: Nodo) -> bool:
	"""Mención dentro del texto (Codex la presenta como botón: «tu carpeta habitual»)."""
	return n.ct == uc.CT_BUTTON and "inlinemention" in n.cls.lower()


def _fragmentos(n: Nodo, padre: int, out: list[tuple[str, int, bool]]) -> None:
	"""Reúne ``(texto, padre, empieza bloque)`` en orden de lectura."""
	if n.oculto or n.ct in (uc.CT_IMAGE, uc.CT_SEPARATOR) or n.aria == "status":
		return
	if n.ct == uc.CT_BUTTON and not _esBotonEnLinea(n):
		return
	if n.ct == uc.CT_LISTITEM:
		# Chromium le da como nombre todo su contenido; sus hijos pueden ser un trozo.
		if n.name.strip():
			out.append(("- " + n.name.strip(), id(n), True))
			return
	elif n.aria == "heading" or n.ct == uc.CT_HYPERLINK or _esBotonEnLinea(n):
		if n.name.strip():
			out.append((n.name, padre, n.aria == "heading"))
		return
	elif n.ct == uc.CT_TEXT and not n.children:
		text = n.name
		if text and not RE_HORA.match(text.strip()) and not RE_CONTADOR.match(text.strip()):
			out.append((text, padre, False))
		return
	for c in n.children:
		_fragmentos(c, id(n), out)


def unirFragmentos(frags: list[tuple[str, int, bool]]) -> str:
	"""Une los trozos: los del mismo padre seguidos (negritas, código), los demás por líneas."""
	res = ""
	prev: int | None = None
	for text, pid, bloque in frags:
		if not text.strip():
			if "\n" in text and res and not res.endswith("\n"):
				res += "\n"
			elif text and res and not res.endswith((" ", "\n")):
				res += " "
			prev = pid
			continue
		if not res or res.endswith("\n"):
			res += text.lstrip()
		elif bloque or (pid != prev and RE_FIN_IDEA.search(res)):
			res = res.rstrip(" ") + "\n" + text.lstrip()
		elif pid == prev or text[0] in ".,;:)" or res.endswith((" ", "(")):
			res += text
		else:
			res += " " + text
		prev = pid
	return re.sub(r"\n{3,}", "\n\n", res).strip()


def textoDe(nodo: Nodo) -> str:
	frags: list[tuple[str, int, bool]] = []
	_fragmentos(nodo, id(nodo), frags)
	return unirFragmentos(frags)


# ---------------------------------------------------------------------- análisis por aplicación
def mensajesClaude(feed: Nodo) -> list[Mensaje]:
	"""Conversación de Claude: un ``article`` por mensaje con un rótulo oculto («Dijiste: ...»)."""
	out: list[Mensaje] = []
	for n in feed.walk():
		if n.aria != "article":
			continue
		rotulo = next((c.name for c in n.walk() if c.aria == "heading" and c.oculto), "")
		autor = USUARIO if re.match(r"\s*(dijiste|you said)\b", rotulo, re.I) else ASISTENTE
		texto = textoDe(n)
		if texto:
			nombre = n.name.lower()
			out.append(Mensaje(autor, texto, "transmisi" in nombre or "stream" in nombre))
	return out


def _lineal(n: Nodo) -> Iterator[Nodo]:
	"""Hojas de la conversación plana de Codex, sin bajar a lo que se lee entero."""
	yield n
	if n.oculto or n.ct in (uc.CT_LISTITEM, uc.CT_HYPERLINK) or n.aria == "heading":
		return
	for c in n.children:
		yield from _lineal(c)


def mensajesCodex(conv: Nodo) -> list[Mensaje]:
	"""Conversación de Codex: lista plana partida por rótulos ocultos («Tú dijiste:», «ChatGPT dijo:»)."""
	bloques: list[tuple[str, Nodo]] = []
	actual: Nodo | None = None
	for n in _lineal(conv):
		if n.aria == "heading" and n.oculto:
			nombre = n.name.strip().lower()
			if nombre.startswith(("última", "ultima", "latest", "last")):
				break
			actual = Nodo()
			bloques.append((USUARIO if re.match(r"(tú|tu|you)\b", nombre) else ASISTENTE, actual))
		elif actual is not None and n is not conv and (not n.children or n.ct == uc.CT_LISTITEM):
			actual.children.append(n)
	out: list[Mensaje] = []
	for autor, bloque in bloques:
		texto = textoDe(bloque)
		if texto:
			out.append(Mensaje(autor, texto))
	return out


def mensajesAntigravity(conv: Nodo) -> list[Mensaje]:
	"""Panel de agente de Antigravity: cada bloque de la conversación, sin el cuadro de escribir."""

	def tieneEntrada(n: Nodo) -> bool:
		return any(c.ct in (uc.CT_COMBOBOX, uc.CT_EDIT) for c in n.walk())

	nivel = conv
	while len(nivel.children) == 1:
		nivel = nivel.children[0]
	if any(c.ct in (uc.CT_COMBOBOX, uc.CT_EDIT) for c in nivel.children):
		# El cuadro de escribir está al mismo nivel: conversación nueva, sin mensajes.
		return []
	out: list[Mensaje] = []
	for hijo in nivel.children:
		if tieneEntrada(hijo):
			continue
		texto = textoDe(hijo)
		if texto and not RE_AVISO_IA.match(texto):
			out.append(Mensaje(ASISTENTE, texto))
	return out


# ---------------------------------------------------------------------- módulo base
_CACHE = None
_CACHE_BUSCAR = None


def _cacheSubarbol():
	global _CACHE
	if _CACHE is None:
		_CACHE = uc.makeCacheRequest((uc.P_NAME, uc.P_CONTROLTYPE, uc.P_ARIAROLE, uc.P_CLASSNAME, uc.P_AUTOMATIONID, uc.P_ARIAPROPERTIES), scope=uc.TreeScope_Subtree)
		# Vista completa: Chromium deja los contenedores fuera de la vista de control.
		_CACHE.TreeFilter = uc.client.RawViewCondition
	return _CACHE


def _cacheBuscar():
	global _CACHE_BUSCAR
	if _CACHE_BUSCAR is None:
		_CACHE_BUSCAR = uc.makeCacheRequest(uc.BASE_PROPERTIES)
		_CACHE_BUSCAR.TreeFilter = uc.client.RawViewCondition
	return _CACHE_BUSCAR


class AsistenteAppModule(BaseAppModule):
	"""Módulo de aplicación de un asistente de IA."""

	scriptCategory = CAT
	#: Nombre con el que se le nombra al avisar.
	nombreAsistente = "IA"

	def __init__(self, processID: int, appName: str | None = None) -> None:
		super().__init__(processID, appName)
		self._iniciarAsistente()

	def _iniciarAsistente(self) -> None:
		self._timer: int | None = None
		self._ventana = 0
		self._trabajando = False
		self._pasadasLibres = 0
		#: Índice del mensaje por el que se va (``None``: el último).
		self._pos: int | None = None

	# ------------------------------------------------- lo que aporta cada aplicación
	def buscarConversacion(self, raiz):
		"""Elemento de la conversación dentro de la ventana, o ``None``."""
		raise NotImplementedError

	def analizar(self, nodo: Nodo) -> list[Mensaje]:
		raise NotImplementedError

	def buscarEntrada(self, raiz):
		"""Cuadro de escribir, o ``None``."""
		raise NotImplementedError

	def estaTrabajando(self, raiz) -> bool | None:
		"""``True`` o ``False``, o ``None`` si no se puede saber ahora."""
		entrada = self.buscarEntrada(raiz)
		if entrada is None:
			return None
		return self._hayBotonDetener(entrada)

	# ------------------------------------------------- acceso a la ventana
	def _buscar(self, raiz, prop: int, valor):
		try:
			return raiz.FindFirstBuildCache(uc.TreeScope_Descendants, uc.createPropertyCondition(prop, valor), _cacheBuscar())
		except Exception:
			return None

	def _hayBotonDetener(self, entrada) -> bool | None:
		"""Busca el botón de detener en lo que rodea al cuadro de escribir."""
		try:
			walker = uc.client.ControlViewWalker
			caja = walker.GetParentElement(entrada)
			caja = walker.GetParentElement(caja) or caja
			arr = caja.FindAll(uc.TreeScope_Descendants, uc.createPropertyCondition(uc.P_CONTROLTYPE, uc.CT_BUTTON))
			for i in range(arr.Length if arr else 0):
				if RE_DETENER.match(arr.GetElement(i).CurrentName or ""):
					return True
			return False
		except Exception:
			return None

	def _raiz(self):
		"""Elemento de la ventana de la aplicación, también con ella en segundo plano."""
		if self._esPrimerPlano():
			fg = api.getForegroundObject()
			el = getattr(fg, "element", None)
			if el is not None:
				self._ventana = int(getattr(fg, "windowHandle", 0) or 0)
				return el
		if self._ventana:
			try:
				return uc.client.ElementFromHandle(self._ventana)
			except Exception:
				self._ventana = 0
		return None

	def _esPrimerPlano(self) -> bool:
		try:
			return bool(self.isForeground())
		except Exception:
			return False

	def mensajes(self) -> list[Mensaje]:
		raiz = self._raiz()
		conv = self.buscarConversacion(raiz) if raiz is not None else None
		if conv is None:
			return []
		try:
			return self.analizar(nodoDesde(conv.BuildUpdatedCache(_cacheSubarbol())))
		except Exception:
			log.debug("No se pudo leer la conversación", exc_info=True)
			return []

	# ------------------------------------------------- vigilancia del fin del turno
	def event_appModule_gainFocus(self) -> None:
		super().event_appModule_gainFocus()
		fg = api.getForegroundObject()
		self._ventana = int(getattr(fg, "windowHandle", 0) or 0) or self._ventana
		if self._timer is None:
			self._timer = queue_handler.callLater(INTERVALO_DELANTE, self._vigilar)

	def terminate(self) -> None:
		if self._timer is not None:
			queue_handler.cancelCallLater(self._timer)
			self._timer = None
		super().terminate()

	def _vigilar(self) -> None:
		self._timer = None
		delante = self._esPrimerPlano()
		try:
			if not self.sleepMode:
				self.comprobarTurno()
		except Exception:
			log.debug("Error vigilando el turno", exc_info=True)
		if self.isAlive:
			self._timer = queue_handler.callLater(INTERVALO_DELANTE if delante else INTERVALO_DETRAS, self._vigilar)

	def comprobarTurno(self) -> None:
		raiz = self._raiz()
		if raiz is None:
			return
		ocupado = self.estaTrabajando(raiz)
		if ocupado is None:
			return
		if ocupado:
			self._trabajando = True
			self._pasadasLibres = 0
			return
		if not self._trabajando:
			return
		self._pasadasLibres += 1
		if self._pasadasLibres >= PASADAS_PARA_TERMINAR:
			self._trabajando = False
			self._pasadasLibres = 0
			self._pos = None
			self.alTerminar()

	def alTerminar(self) -> None:
		ops = conf[ia_opciones.SECTION]
		delante = self._esPrimerPlano()
		if not delante and not ops["avisarEnSegundoPlano"]:
			return
		if ops["sonidoFin"]:
			tones.beep(880, 90)
		if ops["anunciarFin"] and not (ops["leerRespuesta"] and delante):
			speech.speakMessage(_("{nombre} ha terminado").format(nombre=self.nombreAsistente))
		if ops["leerRespuesta"] and delante:
			self._leerUltimaRespuesta()

	# ------------------------------------------------- órdenes
	def _decir(self, texto: str) -> None:
		speech.speakMessage(texto)

	def _rotulo(self, m: Mensaje) -> str:
		return _("Tú") if m.autor == USUARIO else self.nombreAsistente

	def _decirMensaje(self, m: Mensaje, indice: int, total: int) -> None:
		self._decir(_("{autor}, {n} de {total}: {texto}").format(autor=self._rotulo(m), n=indice + 1, total=total, texto=m.texto[:LARGO_VOZ]))

	def _leerUltimaRespuesta(self) -> bool:
		msgs = self.mensajes()
		for i in range(len(msgs) - 1, -1, -1):
			if msgs[i].autor == ASISTENTE:
				self._pos = i
				self._decirMensaje(msgs[i], i, len(msgs))
				return True
		self._decir(_("Todavía no hay ninguna respuesta"))
		return False

	def _mover(self, cambio) -> None:
		msgs = self.mensajes()
		if not msgs:
			self._decir(_("No se encuentra ninguna conversación"))
			return
		actual = self._pos if self._pos is not None and self._pos < len(msgs) else len(msgs)
		nuevo = cambio(actual, len(msgs))
		if nuevo < 0 or nuevo >= len(msgs):
			tones.beep(220, 80)
			self._decir(_("Primer mensaje") if nuevo < 0 else _("Último mensaje"))
			return
		self._pos = nuevo
		self._decirMensaje(msgs[nuevo], nuevo, len(msgs))

	@script(description=_("Lee el mensaje anterior de la conversación sin mover el foco"), gesture="kb:tiresias+control+upArrow", category=CAT, speakOnDemand=True)
	def script_mensajeAnterior(self, gesture) -> None:
		self._mover(lambda pos, _total: pos - 1)

	@script(description=_("Lee el mensaje siguiente de la conversación sin mover el foco"), gesture="kb:tiresias+control+downArrow", category=CAT, speakOnDemand=True)
	def script_mensajeSiguiente(self, gesture) -> None:
		self._mover(lambda pos, _total: pos + 1)

	@script(description=_("Lee el primer mensaje de la conversación"), gesture="kb:tiresias+control+home", category=CAT, speakOnDemand=True)
	def script_primerMensaje(self, gesture) -> None:
		self._mover(lambda _pos, _total: 0)

	@script(description=_("Lee el último mensaje de la conversación"), gesture="kb:tiresias+control+end", category=CAT, speakOnDemand=True)
	def script_ultimoMensaje(self, gesture) -> None:
		self._mover(lambda _pos, total: total - 1)

	@script(description=_("Lee la última respuesta del asistente; dos pulsaciones la copian al portapapeles"), gesture="kb:tiresias+alt+u", category=CAT, speakOnDemand=True)
	def script_ultimaRespuesta(self, gesture) -> None:
		if inputCore.getLastScriptRepeatCount() >= 1:
			msgs = self.mensajes()
			resp = next((m for m in reversed(msgs) if m.autor == ASISTENTE), None)
			if resp is not None and api.copyToClip(resp.texto):
				self._decir(_("Respuesta copiada"))
			return
		self._leerUltimaRespuesta()

	@script(description=_("Abre el mensaje por el que vas en una ventana de texto para leerlo con las flechas y copiarlo"), gesture="kb:tiresias+alt+y", category=CAT)
	def script_abrirMensaje(self, gesture) -> None:
		from tiresias import gui

		msgs = self.mensajes()
		if not msgs:
			self._decir(_("No se encuentra ninguna conversación"))
			return
		i = self._pos if self._pos is not None and self._pos < len(msgs) else len(msgs) - 1
		gui.showBrowseableMessage(msgs[i].texto, self._rotulo(msgs[i]))

	@script(description=_("Lleva el foco al cuadro de escribir"), gesture="kb:tiresias+alt+p", category=CAT)
	def script_irAEscribir(self, gesture) -> None:
		raiz = self._raiz()
		entrada = self.buscarEntrada(raiz) if raiz is not None else None
		obj = UIAObject.fromElement(entrada) if entrada is not None else None
		if obj is None:
			self._decir(_("No se encuentra el cuadro de escribir"))
			return
		obj.setFocus()

	@script(description=_("Dice si el asistente está trabajando y cuántos mensajes hay"), gesture="kb:tiresias+alt+q", category=CAT, speakOnDemand=True)
	def script_estado(self, gesture) -> None:
		raiz = self._raiz()
		ocupado = self.estaTrabajando(raiz) if raiz is not None else None
		total = len(self.mensajes())
		if ocupado:
			estado = _("{nombre} está trabajando").format(nombre=self.nombreAsistente)
		elif ocupado is None:
			estado = _("No se sabe si {nombre} está trabajando").format(nombre=self.nombreAsistente)
		else:
			estado = _("{nombre} está esperando").format(nombre=self.nombreAsistente)
		if total == 1:
			self._decir(_("{estado}, 1 mensaje").format(estado=estado))
		else:
			self._decir(_("{estado}, {n} mensajes").format(estado=estado, n=total))

	@script(description=_("Activa o desactiva la lectura automática de la respuesta al terminar"), gesture="kb:tiresias+alt+z", category=CAT)
	def script_alternarLectura(self, gesture) -> None:
		ops = conf[ia_opciones.SECTION]
		ops["leerRespuesta"] = not ops["leerRespuesta"]
		self._decir(_("Leer la respuesta al terminar, activado") if ops["leerRespuesta"] else _("Leer la respuesta al terminar, desactivado"))
