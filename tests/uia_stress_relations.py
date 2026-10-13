"""Prueba de estrés de las propiedades UIA con matrices de elementos.

Se ejecuta en un proceso aparte (un fallo del montón cierra el proceso entero)
y devuelve 0 si todo fue bien. Modos (primer argumento):

- ``local``: llama miles de veces al manejador de eventos de Tiresias a través
  de su tabla COM, como lo hace UIA, con un VARIANT de texto (BSTR) y otro con
  una matriz de elementos (VT_UNKNOWN). Antes del arreglo, comtypes liberaba
  la copia del VARIANT del llamador (VariantClear) y UIA lo liberaba otra vez:
  doble liberación y ``0xc0000374`` (corrupción del montón).
- ``edge <pid> [segundos]``: con una página de prueba abierta en Edge (campo con
  ``aria-controls`` y ``aria-describedby`` que cambian sin parar), lee
  ControllerFor, DescribedBy, FlowsTo, AnnotationObjects y LabeledBy miles de
  veces con los accesores tipados (``UIAObject.relationElements``) y recibe sus
  eventos de cambio de propiedad con el manejador real.
"""

from __future__ import annotations

import os
import sys
import time

sys.coinit_flags = 0  # MTA, como el hilo del núcleo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import comtypes  # noqa: E402
from comtypes.automation import VARIANT  # noqa: E402

from tiresias import queue_handler  # noqa: E402
from tiresias.a11y import uia_client as uc  # noqa: E402
from tiresias.a11y import uia_handler  # noqa: E402

_queued = [0]


def _noQueue(func, *args, **kwargs):
	# El núcleo no está en marcha: solo se cuenta lo que se habría encolado.
	_queued[0] += 1


queue_handler.queueFunction = _noQueue


#: TIRESIAS_STRESS_UNFIXED=1 reproduce el comportamiento ANTERIOR al arreglo
#: (sin vaciar el VARIANT y leyendo las relaciones como VARIANT) para comprobar
#: que la prueba detecta el fallo.
UNFIXED = os.environ.get("TIRESIAS_STRESS_UNFIXED") == "1"


class _UnfixedHandler(uia_handler._EventHandler):
	def IUIAutomationPropertyChangedEventHandler_HandlePropertyChangedEvent(self, sender, propertyId, newValue):
		_queued[0] += 1


def _handlerPointer():
	handler = _UnfixedHandler() if UNFIXED else uia_handler._EventHandler()
	return handler, handler.QueryInterface(uc.UIA.IUIAutomationPropertyChangedEventHandler)


def runLocal(rounds: int = 20000) -> int:
	uc.initialize()
	root = uc.client.GetRootElement()
	handler, ptr = _handlerPointer()
	arr = root.FindAll(uc.TreeScope_Children, uc.client.CreateTrueCondition())
	for i in range(rounds):
		v = VARIANT("Texto de prueba %d" % i)
		ptr.HandlePropertyChangedEvent(root, uc.P_NAME, v)
		# El llamador (UIA) libera su VARIANT al volver: si el manejador ya lo
		# había liberado, esto es la segunda liberación.
		del v
		w = VARIANT()
		w.value = arr
		ptr.HandlePropertyChangedEvent(root, uc.P_CONTROLLERFOR, w)
		del w
		if i % 2000 == 0:
			# Usa el montón entre tanda y tanda para que el daño se note.
			_ = [str(n) * 50 for n in range(2000)]
	# La matriz debe seguir viva y utilizable.
	n = arr.Length
	for i in range(n):
		arr.GetElement(i).CurrentName
	print("local: %d rondas sin fallos (%d encolados)" % (rounds, _queued[0]))
	return 0


def _findField(pid: int, timeout: float = 20.0):
	cond = uc.client.CreateAndCondition(
		uc.client.CreatePropertyCondition(uc.P_PROCESSID, pid),
		uc.client.CreatePropertyCondition(uc.P_AUTOMATIONID, "q"),
	)
	deadline = time.time() + timeout
	root = uc.client.GetRootElement()
	while time.time() < deadline:
		try:
			for child in _children(root):
				el = child.FindFirst(uc.TreeScope_Descendants, cond)
				if el:
					return el
		except comtypes.COMError:
			pass
		time.sleep(0.5)
	return None


def _children(root):
	arr = root.FindAll(uc.TreeScope_Children, uc.client.CreateTrueCondition())
	return [arr.GetElement(i) for i in range(arr.Length)] if arr else []


def runEdge(pids: list[int], seconds: float = 20.0) -> int:
	from tiresias.objects.uia import UIAObject

	uc.initialize()
	el = None
	deadline = time.time() + 30
	while el is None and time.time() < deadline:
		root = uc.client.GetRootElement()
		for child in _children(root):
			try:
				if child.CurrentProcessId not in pids and child.CurrentClassName != "Chrome_WidgetWin_1":
					continue
				found = child.FindFirst(uc.TreeScope_Descendants, uc.client.CreatePropertyCondition(uc.P_AUTOMATIONID, "q"))
			except comtypes.COMError:
				continue
			if found:
				el = found
				break
		if el is None:
			time.sleep(0.5)
	if el is None:
		print("edge: no se encontró el campo de prueba")
		return 2
	handler, ptr = _handlerPointer()
	# El campo hace de foco: sus eventos pasan los filtros y se cuentan.
	uia_handler._focusRid = uc.runtimeIdOf(el)
	import ctypes

	props = [uc.P_CONTROLLERFOR, uc.P_NAME, uc.P_DESCRIBEDBY, uc.P_FLOWSTO]
	arr = (ctypes.c_int * len(props))(*props)
	uc.client.AddPropertyChangedEventHandlerNativeArray(el, uc.TreeScope_Element, uc.baseCacheRequest, handler, arr, len(props))
	reads = 0
	withControls = 0
	end = time.time() + seconds
	while time.time() < end:
		obj = UIAObject(el)
		for key in ("controllerFor", "describedBy", "flowsTo", "details"):
			if UNFIXED:
				val = el.GetCurrentPropertyValueEx(UIAObject._RELATIONS[key], True)
				items = list(val) if isinstance(val, (list, tuple)) else ([val] if val and not uc.isNotSupported(val) else [])
			else:
				items = obj.relationElements(key)
			if key == "controllerFor" and items:
				withControls += 1
			reads += 1
		if not UNFIXED:
			obj.event_controllerForChange()
		obj.name  # noqa: B018 (LabeledBy si no tiene nombre)
		reads += 1
	uc.client.RemoveAllEventHandlers()
	print("edge: %d lecturas, %d con lista asociada, %d eventos recibidos" % (reads, withControls, _queued[0]))
	return 0 if reads else 3


if __name__ == "__main__":
	mode = sys.argv[1] if len(sys.argv) > 1 else "local"
	if mode == "local":
		sys.exit(runLocal(int(sys.argv[2]) if len(sys.argv) > 2 else 20000))
	pids = [int(p) for p in sys.argv[2].split(",")] if len(sys.argv) > 2 else []
	sys.exit(runEdge(pids, float(sys.argv[3]) if len(sys.argv) > 3 else 20.0))
