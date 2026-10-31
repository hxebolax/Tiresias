"""Descripción con IA de las imágenes sin texto alternativo.

Usa los proveedores de IA de Tiresias (*Opciones, Inteligencia artificial*)
igual que el etiquetado automático del núcleo: se captura cada imagen con un
margen de contexto, se pide un texto alternativo breve y se guarda en el
almacén de textos de IA de Tiresias (``ai.labelstore``), que el búfer ya usa
como nombre al reconstruirse. Nada se envía sin el proveedor configurado ni
sin que el usuario haya aceptado el aviso de privacidad de las imágenes.

Las peticiones van en un hilo propio, una tras otra, con un máximo por tanda.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from tiresias.log import getLogger

log = getLogger("arregloWeb")

PROMPT = (
	"Esta imagen muestra, en el centro, una imagen sin texto alternativo de una página web (el resto es contexto). "
	"Escribe un texto alternativo de una sola frase breve que diga qué muestra o, si es un icono, para qué sirve. "
	"Si contiene texto, transcríbelo. Responde solo con ese texto. Si no se puede saber, responde solo: ?"
)


def describir(doc: Any, nodos: list, maximo: int, alTerminar: Callable[[int, int, str], None] | None = None) -> bool:
	"""Describe hasta ``maximo`` imágenes de ``nodos``. Devuelve ``False`` si no se ha pedido nada.

	``alTerminar(hechas, fallidas, error)`` se llama en el núcleo al acabar.
	"""
	from tiresias import speech
	from tiresias.ai import assistant

	provider = assistant.checkProvider(quiet=False)
	if provider is None:
		return False
	nodos = [n for n in nodos if n is not None][: max(1, maximo)]
	if not nodos:
		speech.speakMessage("No hay imágenes que describir.")
		return False

	def arrancar() -> None:
		speech.speakMessage(f"Describiendo {len(nodos)} imágenes con IA; se avisará al terminar.")
		threading.Thread(target=_trabajo, args=(doc, nodos, provider, alTerminar), name="arregloWeb-IA", daemon=True).start()

	if assistant.privacyAccepted(provider):
		arrancar()
	else:
		assistant.withImagePrivacy(arrancar)
	return True


def _trabajo(doc: Any, nodos: list, provider: Any, alTerminar: Callable | None) -> None:
	from tiresias import imaging, queue_handler
	from tiresias.ai import assistant, labelstore
	from tiresias.ai.autolabel import cleanAltText
	from tiresias.ai.providers import AIError, Message

	hechas = 0
	fallidas = 0
	error = ""
	try:
		docKey = doc._documentKey()
	except Exception:
		docKey = ""
	hwnd = assistant.rootWindow(getattr(doc, "rootObject", None))
	for nodo in nodos:
		try:
			rect = assistant.liveRect(nodo.element) if nodo.element is not None else None
			rect = assistant.paddedRect(rect or nodo.location) if (rect or nodo.location) else None
			if rect is None:
				fallidas += 1
				continue
			png = assistant._imageToPng(imaging.captureRect(rect, hwnd) if hwnd else imaging.captureRect(rect))
			reply = provider.chat([Message("user", PROMPT, [png])], assistant.systemPrompt(), maxTokens=2000, effort="low")
			texto = cleanAltText(reply.text)
			if not texto or texto == "?":
				fallidas += 1
				continue
			labelstore.setLabel(docKey, nodo, texto)
			hechas += 1
		except AIError as e:
			log.warning("Arreglo web: descripción con IA fallida: %s", e)
			error = str(e)
			if getattr(e, "isFatal", False):
				break
			fallidas += 1
		except Exception:
			log.warning("Arreglo web: descripción con IA fallida", exc_info=True)
			fallidas += 1

	def fin() -> None:
		if hechas:
			try:
				doc.requestRebuild()
			except Exception:
				log.debug("No se pudo reconstruir el documento tras describir imágenes", exc_info=True)
		if alTerminar is not None:
			alTerminar(hechas, fallidas, error)

	queue_handler.queueFunction(fin)
