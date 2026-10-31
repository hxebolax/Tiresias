"""Reglas de arreglo y su aplicación sobre los nodos del búfer.

Una regla es un diccionario guardable en JSON::

	{"tipo": "nombre", "huella": {...}, "nombre": "Informe anual", "motivo": "url"}

Tipos:

- ``nombre``: da nombre a un enlace, botón o imagen (o cambia uno inútil).
  Para los enlaces se sustituye también su contenido (los hijos no se
  recorren): así el texto del búfer es el nombre nuevo y no «gráfico».
- ``etiqueta``: etiqueta un campo de formulario sin nombre.
- ``boton``: presenta como botón un elemento genérico pulsable.
- ``encabezado``: presenta como encabezado (``nivel`` 1-6) un texto que lo parece.
- ``region``: presenta un bloque como punto de referencia (``landmark``).
- ``maquetacion``: trata una tabla como tabla de maquetación.
- ``ocultar``: la ocultación la hace la web flexible de Tiresias; la regla
  solo guarda la regla ``flex`` equivalente para poder quitarla.

La **huella** identifica el elemento sin depender de su posición en el
texto, con datos que ya se conocen en el momento de crear el nodo (antes de
recorrer sus hijos): tipo de control UIA y, por este orden, el ``id`` HTML
(AutomationId), el destino del enlace y su nombre, el nombre, o la clase, el
nombre del padre y cuántos hermanos le preceden.
"""

from __future__ import annotations

import json
from typing import Any

from tiresias.objects.roles import HEADING_ROLES, Role, State

#: Marca (en ``node.aria``) de los nodos cuyo contenido sustituye el nombre de la regla.
MARCA_SUSTITUYE = "_arregloWebSustituye"

#: Roles del búfer en los que un nombre sustituye al contenido.
ROLES_CON_CONTENIDO = {Role.LINK}


# ====================================================================== huellas
def huella(node: Any, ct: int) -> dict:
	"""Huella estable de un nodo (ver el docstring del módulo)."""
	h: dict[str, Any] = {"ct": int(ct or 0)}
	if node.automationId:
		h["id"] = str(node.automationId)[:120]
		return h
	url = node.url if node.role == Role.LINK else ""
	if url:
		h["url"] = str(url)[:300]
	name = (node.name or "").strip()
	if name:
		h["name"] = name[:80]
		return h
	if url:
		return h
	h["cls"] = (node.className or "")[:60]
	parent = node.parent
	if parent is not None:
		h["p"] = (parent.name or "")[:40]
		# Cuántos hermanos le preceden: al crear el nodo, los que ya están en
		# ``parent.children``; en el búfer terminado, su posición en la lista.
		hermanos = parent.children
		h["n"] = next((i for i, c in enumerate(hermanos) if c is node), len(hermanos))
	return h


def claveHuella(h: dict) -> str:
	"""Cadena única de una huella (para indexar las reglas)."""
	return json.dumps(h, sort_keys=True, ensure_ascii=False)


def claveRegla(regla: dict) -> str:
	"""Clave de una regla: tipo + huella (las de ocultar, por su regla flexible)."""
	if regla.get("tipo") == "ocultar":
		return "ocultar:" + json.dumps(regla.get("flex") or {}, sort_keys=True, ensure_ascii=False)
	return regla.get("tipo", "") + ":" + claveHuella(regla.get("huella") or {})


def describirHuella(h: dict) -> str:
	if h.get("id"):
		return "#" + h["id"]
	if h.get("name"):
		return "«" + h["name"] + "»"
	if h.get("url"):
		return h["url"]
	partes = []
	if h.get("cls"):
		partes.append("." + h["cls"])
	if h.get("p"):
		partes.append("en «" + h["p"] + "»")
	if "n" in h:
		partes.append("posición " + str(h["n"] + 1))
	return " ".join(partes) or "?"


# ====================================================================== reglas de un sitio
class ReglasSitio:
	"""Reglas de un sitio indexadas por clave de huella (se consultan por cada nodo)."""

	def __init__(self, sitio: str, reglas: list[dict]) -> None:
		self.sitio = sitio
		self.reglas = list(reglas)
		self.porClave: dict[str, dict] = {}
		for r in self.reglas:
			if r.get("tipo") != "ocultar" and r.get("huella"):
				self.porClave[claveHuella(r["huella"])] = r
		#: Alguna regla sustituye el contenido de un elemento (hay que mirar los antecesores).
		self.sustituye = any(r.get("tipo") in ("nombre", "boton") for r in self.reglas)

	def __len__(self) -> int:
		return len(self.reglas)

	def reglaPara(self, node: Any, ct: int) -> dict | None:
		if not self.porClave:
			return None
		return self.porClave.get(claveHuella(huella(node, ct)))


def _rolEncabezado(nivel: int) -> Role:
	nivel = max(1, min(6, int(nivel or 2)))
	return Role(Role.HEADING1 + nivel - 1)


def aplicar(reglas: ReglasSitio, node: Any, ct: int) -> Any:
	"""Aplica a ``node`` la regla que le corresponda. Devuelve el nodo o ``None``.

	Es el manejador de ``browse.buffer.filter_node``: se ejecuta por cada
	nodo al construir el búfer, así que es barato (una búsqueda en un
	diccionario) y nunca lanza excepciones hacia fuera.
	"""
	if node is None:
		return None
	if reglas.sustituye:
		# Contenido sustituido por el nombre de un antecesor: fuera del búfer.
		p = node.parent
		while p is not None:
			if MARCA_SUSTITUYE in p.aria:
				return None
			p = p.parent
	regla = reglas.reglaPara(node, ct)
	if regla is None:
		return node
	tipo = regla.get("tipo")
	if tipo == "nombre":
		nombre = (regla.get("nombre") or "").strip()
		if nombre:
			node.name = nombre
			node.unlabeled = False
			if node.role in ROLES_CON_CONTENIDO:
				node.aria[MARCA_SUSTITUYE] = "1"
	elif tipo == "etiqueta":
		nombre = (regla.get("nombre") or "").strip()
		if nombre and not node.name:
			node.name = nombre
	elif tipo == "boton":
		nombre = (regla.get("nombre") or "").strip() or node.name
		node.role = Role.BUTTON
		node.name = nombre
		node.clickable = False
		node.states.discard(State.CLICKABLE)
		node.aria[MARCA_SUSTITUYE] = "1"
	elif tipo == "encabezado":
		if node.role not in HEADING_ROLES:
			node.role = _rolEncabezado(regla.get("nivel", 2))
			node.level = int(node.role) - int(Role.HEADING1) + 1
	elif tipo == "region":
		if node.role != Role.LANDMARK:
			node.role = Role.LANDMARK
			node.landmark = regla.get("landmark") or "principal"
	elif tipo == "maquetacion":
		node.layoutTable = True
	return node


# ====================================================================== descripción para las listas
ETIQUETAS_TIPO = {
	"nombre": "Nombre",
	"etiqueta": "Etiqueta de campo",
	"boton": "Botón",
	"encabezado": "Encabezado",
	"region": "Región",
	"maquetacion": "Tabla de maquetación",
	"ocultar": "Oculto",
}


def describirRegla(regla: dict) -> str:
	tipo = regla.get("tipo", "")
	etiqueta = ETIQUETAS_TIPO.get(tipo, tipo)
	if tipo == "ocultar":
		try:
			from tiresias.browse import flexweb

			return f"{etiqueta}: {flexweb.describeRule(regla.get('flex') or {})}"
		except Exception:
			return etiqueta
	que = describirHuella(regla.get("huella") or {})
	if tipo in ("nombre", "etiqueta", "boton") and regla.get("nombre"):
		return f"{etiqueta} «{regla['nombre']}»: {que}"
	if tipo == "encabezado":
		return f"{etiqueta} de nivel {regla.get('nivel', 2)}: {que}"
	if tipo == "region":
		return f"{etiqueta} {regla.get('landmark', 'principal')}: {que}"
	return f"{etiqueta}: {que}"
