"""Combinación de capturas sucesivas de una terminal (funciones puras).

Las terminales no exponen sus cambios de forma uniforme: unas devuelven todo
el historial, otras una ventana deslizante y las aplicaciones de pantalla
completa redibujan el mismo bloque. Este módulo convierte esas instantáneas
en sustituciones pequeñas sobre el documento del visor, de modo que el
cursor, la selección y la posición de lectura no se mueven.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ActualizacionDocumento:
	"""Una sustitución de texto en el documento del visor."""

	inicio: int
	fin: int
	texto: str
	nuevos_caracteres: int = 0
	reinicio: bool = False

	@property
	def es_agregado(self) -> bool:
		return self.inicio == self.fin


def normalizar_captura(texto: str) -> str:
	"""Normaliza los saltos de línea sin destruir espacios significativos."""
	return (texto or "").replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")


def solapamiento_lineas(anterior: str, nueva: str) -> int:
	"""Cuántas líneas del final de ``anterior`` abren ``nueva``.

	Algoritmo KMP sobre líneas: escala linealmente con historiales grandes.
	"""
	lineas_anteriores = anterior.splitlines()
	lineas_nuevas = nueva.splitlines()
	if not lineas_anteriores or not lineas_nuevas:
		return 0
	prefijo = [0] * len(lineas_nuevas)
	j = 0
	for i in range(1, len(lineas_nuevas)):
		while j and lineas_nuevas[i] != lineas_nuevas[j]:
			j = prefijo[j - 1]
		if lineas_nuevas[i] == lineas_nuevas[j]:
			j += 1
			prefijo[i] = j
	estado = 0
	for indice, linea in enumerate(lineas_anteriores):
		while estado and linea != lineas_nuevas[estado]:
			estado = prefijo[estado - 1]
		if linea == lineas_nuevas[estado]:
			estado += 1
			if estado == len(lineas_nuevas):
				if indice == len(lineas_anteriores) - 1:
					return estado
				estado = prefijo[estado - 1]
	return estado


def calcular_actualizacion(
	documento: str,
	captura_anterior: str,
	nueva_captura: str,
	conservar_historial: bool = True,
) -> ActualizacionDocumento | None:
	"""Cambio mínimo para aplicar ``nueva_captura`` al documento del visor.

	Con ``conservar_historial`` se acumulan las líneas que desaparecen del
	búfer de la terminal. Los redibujados y las líneas de progreso se
	actualizan en su sitio. Devuelve ``None`` si no hay cambios.
	"""
	documento = normalizar_captura(documento)
	anterior = normalizar_captura(captura_anterior)
	nueva = normalizar_captura(nueva_captura)
	if nueva == anterior:
		return None
	if not anterior:
		separador = "\n" if documento and nueva else ""
		return ActualizacionDocumento(len(documento), len(documento), separador + nueva, len(nueva))
	# Caso habitual: la terminal añadió texto al final.
	if nueva.startswith(anterior):
		delta = nueva[len(anterior):]
		return ActualizacionDocumento(len(documento), len(documento), delta, len(delta))
	# Cambió la línea activa o una cola pequeña (porcentajes, indicadores, prompts).
	prefijo = 0
	limite = min(len(anterior), len(nueva))
	while prefijo < limite and anterior[prefijo] == nueva[prefijo]:
		prefijo += 1
	if prefijo:
		inicio_linea = anterior.rfind("\n", 0, prefijo) + 1
		lineas_comunes = anterior.count("\n", 0, inicio_linea)
		if lineas_comunes >= 2 or prefijo >= int(len(anterior) * 0.25):
			base = len(documento) - len(anterior) if documento.endswith(anterior) else 0
			inicio = base + inicio_linea
			return ActualizacionDocumento(inicio, len(documento), nueva[inicio_linea:], max(0, len(nueva) - len(anterior)))
	# El búfer se desplazó: se conserva lo antiguo y se añade solo lo nuevo.
	solapadas = solapamiento_lineas(anterior, nueva)
	if conservar_historial and solapadas:
		lineas = nueva.splitlines()
		delta = "\n".join(lineas[solapadas:])
		if delta:
			delta = "\n" + delta
		return ActualizacionDocumento(len(documento), len(documento), delta, len(delta))
	# Pantalla completa redibujada o sesión limpiada.
	if documento.endswith(anterior):
		inicio = len(documento) - len(anterior)
		return ActualizacionDocumento(inicio, len(documento), nueva, len(nueva), True)
	return ActualizacionDocumento(0, len(documento), nueva, len(nueva), True)


def recortar_documento(texto: str, max_caracteres: int) -> tuple[str, int]:
	"""Limita la memoria quitando líneas completas del principio.

	Devuelve el texto recortado y cuántos caracteres se han quitado.
	"""
	if max_caracteres <= 0 or len(texto) <= max_caracteres:
		return texto, 0
	inicio = len(texto) - max_caracteres
	salto = texto.find("\n", inicio)
	if salto == -1:
		return texto[-max_caracteres:], len(texto) - max_caracteres
	eliminados = salto + 1
	return texto[eliminados:], eliminados


def trasladar_posicion(posicion: int, actualizacion: ActualizacionDocumento) -> int:
	"""Nueva posición de ``posicion`` tras aplicar ``actualizacion``."""
	delta = len(actualizacion.texto) - (actualizacion.fin - actualizacion.inicio)
	if posicion <= actualizacion.inicio:
		return posicion
	if posicion >= actualizacion.fin:
		return posicion + delta
	return actualizacion.inicio


def adaptar_intervalo(base: int, actual: int, duracion_ms: int, maximo: int = 10000) -> int:
	"""Intervalo de seguimiento adaptado a lo que tarda una captura.

	Si capturar cuesta más que el periodo, se alarga (hasta ``maximo``); cuando
	la terminal se recupera vuelve hacia ``base`` de 250 en 250 ms.
	"""
	objetivo = min(maximo, max(base, int(duracion_ms * 1.5)))
	if objetivo < actual:
		objetivo = max(objetivo, actual - 250)
	return objetivo
