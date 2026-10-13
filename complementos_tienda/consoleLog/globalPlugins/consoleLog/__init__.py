"""Visor de consola (consoleLog) para Tiresias.

Visor accesible para consultar, seguir en tiempo real, buscar, copiar,
guardar y analizar la salida de las consolas de Windows (Console Host,
Windows Terminal y emuladores de terceros) sin mover la posición de lectura;
lanzador de terminales, alertas, herramientas para registros y formatos de
desarrollo, y chat e informes de inteligencia artificial en HTML navegable.

Las órdenes no tienen gestos por defecto (como en el original): se asignan
en *Preferencias, Gestos de entrada*, categoría «Visor de consola».

Copyright (C) 2024-2026 Héctor J. Benítez Corredera <xebolax@gmail.com>.
Licencia Pública General de GNU. Versión para Tiresias.
"""

from __future__ import annotations

from dataclasses import dataclass

from tiresias.baseobject import script
from tiresias.log import getLogger
from tiresias.plugins import GlobalPlugin as _Base

from . import avisos
from . import configuracion as cfg
from .definiciones_ventana import ARCHIVO as ARCHIVO_DEFINICIONES
from .definiciones_ventana import GestorDefinicionesVentana
from .deteccion import DestinoConsola, DetectorTerminal, es_ventana_consola, etiqueta_consola, instantanea, obtener_identidad
from .herramientas import GestorHerramientas
from .lanzador import GestorLanzador
from .lectores import GestorLectores
from .procesador_texto import ProcesadorTexto
from .protector_rafagas import ProtectorRafagas
from .registro_visores import RegistroVisores

log = getLogger("consoleLog")


@dataclass
class Captura:
	"""Texto procesado de una captura: con y sin las regiones silenciadas."""

	texto: str
	sin_filtrar: str

	def __bool__(self) -> bool:
		return bool(self.texto and self.texto.strip())


def _modoSeguro() -> bool:
	try:
		from tiresias.config.policy import policy

		return bool(policy.secureMode)
	except Exception:
		return False


class ComplementoConsoleLog(_Base):
	def __init__(self) -> None:
		super().__init__()
		cfg.registrarValores()
		self._registro = RegistroVisores()
		self.definiciones = GestorDefinicionesVentana(cfg.rutaDatos(ARCHIVO_DEFINICIONES))
		self.detector = DetectorTerminal()
		self.procesador = ProcesadorTexto()
		self.lanzador = GestorLanzador()
		self.herramientas = GestorHerramientas(self)
		self.herramientas.cargar_plugins(cfg.herramientasHabilitadas())
		self._lector_copia = GestorLectores()
		self._lanzador_abierto = False
		self.protector = ProtectorRafagas()
		if cfg.valor("proteccionRafagas"):
			self.protector.instalar()
		try:
			from .interfaz import opciones

			opciones.complemento = self
			opciones.registrar_panel()
		except Exception:
			log.exception("consoleLog: no se pudo añadir la categoría a las opciones")

	def terminate(self) -> None:
		try:
			for gestor in self._registro.recursos_pendientes():
				if gestor:
					gestor.cancelar_lectura()
			from tiresias.gui.helpers import runOnGui

			for visor in self._registro.visores():
				runOnGui(visor.cerrar_desde_complemento)
			self._registro.limpiar()
			self._lector_copia.cancelar_lectura()
			self.protector.desinstalar()
			self.herramientas.descargar_plugins()
			from .interfaz import opciones

			opciones.retirar_panel()
			if opciones.complemento is self:
				opciones.complemento = None
		except Exception:
			log.exception("consoleLog: error al terminar el complemento")

	# ------------------------------------------------------------------ consola actual
	def destino_actual(self) -> DestinoConsola:
		from tiresias import api

		return instantanea(api.getForegroundObject(), api.getFocusObject())

	@staticmethod
	def _bloqueada() -> bool:
		"""Pantalla de bloqueo o escritorio seguro: no se lee nada."""
		try:
			from tiresias import api
			from tiresias.a11y import system

			return system.isSecureDesktopActive() or system.isSecureObject(api.getForegroundObject())
		except Exception:
			return False

	def procesar_texto_consola(self, texto: str, destino: DestinoConsola | None = None) -> Captura:
		"""Limpieza ANSI, perfil de la terminal, bidireccional, símbolos y regiones."""
		if not texto:
			return Captura("", "")
		procesado = texto
		if cfg.valor("habilitarProcesamiento"):
			limpiar = bool(cfg.valor("limpiarAnsi"))
			condensar = bool(cfg.valor("condensarSimbolos"))
			simbolos = str(cfg.valor("simbolosACondensar") or "")
			if cfg.valor("detectarTerminal") and destino is not None:
				perfil = self.detector.obtener_perfil(self.detector.detectar_aplicacion(destino))
				if perfil is not None and cfg.valor("usarPerfilTerminal"):
					if perfil.limpiar_ansi is not None:
						limpiar = perfil.limpiar_ansi
					if perfil.condensar_simbolos is not None:
						condensar = perfil.condensar_simbolos
					if perfil.simbolos_a_condensar is not None:
						simbolos = perfil.simbolos_a_condensar
			procesado = self.procesador.procesar_texto(
				texto,
				limpiar_ansi=limpiar,
				condensar_simbolos=condensar,
				procesar_bidi=bool(cfg.valor("procesarBidi")),
				procesar_emoji=bool(cfg.valor("procesarEmoji")),
				simbolos=simbolos,
			)
		return Captura(self.definiciones.aplicar_filtros(procesado), procesado)

	def preparador(self, destino: DestinoConsola | None):
		"""Función que procesa la captura en el hilo de lectura."""
		return lambda texto: self.procesar_texto_consola(texto, destino)

	def vigilar_regiones(self, texto: str, anunciar: bool = True) -> None:
		"""Anuncia los cambios de las regiones en modo «monitorizar»."""
		if not self.definiciones.hay_monitorizadas():
			return
		cambios = self.definiciones.detectar_cambios(texto or "")
		if not anunciar:
			return
		for clave, nuevo in cambios.items():
			d = self.definiciones.obtener_definicion(clave)
			resumen = " ".join((nuevo or "").split())
			if len(resumen) > 300:
				resumen = resumen[:297] + "..."
			avisos.anunciar("Cambio en {}: {}".format(d.nombre if d else clave, resumen or "región vacía"))

	# ------------------------------------------------------------------ visor
	@script(description="Muestra el visor de consola", category=cfg.CATEGORIA)
	def script_mostrarVisorConsola(self, gesture) -> None:
		if self._bloqueada():
			return
		destino = self.destino_actual()
		if not es_ventana_consola(destino):
			avisos.anunciar("Esta no es una ventana de consola.")
			return
		self.abrir_visor(destino)

	def abrir_visor(self, destino: DestinoConsola, gestor: GestorLectores | None = None) -> bool:
		identidad = obtener_identidad(destino)
		if identidad is None:
			avisos.anunciar("No se pudo identificar la ventana de la consola.")
			return False
		existente = self._registro.obtener(identidad)
		if existente is not None:
			from tiresias.gui.helpers import runOnGui

			runOnGui(existente.activar)
			avisos.anunciar("Ya hay un visor abierto para esta consola.")
			return False
		if self._registro.esta_pendiente(identidad):
			avisos.anunciar("El visor de esta consola ya se está abriendo.")
			return False
		# Cada visor tiene su propio gestor de lectura.
		gestor = gestor or GestorLectores()
		if not self._registro.reservar(identidad, gestor):
			return False
		iniciada = gestor.leer_consola(
			destino,
			lambda captura: self._mostrar_visor(captura, destino, identidad, gestor),
			lambda error: self._error_visor(identidad, gestor, error),
			emitir_beep=True,
			procesar=self.preparador(destino),
		)
		if not iniciada:
			self._registro.liberar_reserva(identidad, gestor)
			avisos.anunciar("No se pudo iniciar la lectura de la consola.")
		return iniciada

	def _mostrar_visor(self, captura, destino, identidad, gestor) -> None:
		"""En el hilo de la interfaz, con la captura inicial ya procesada."""
		if not self._registro.coincide_reserva(identidad, gestor):
			return
		texto = getattr(captura, "texto", captura) or ""
		if not texto.strip():
			self._registro.liberar_reserva(identidad, gestor)
			avisos.anunciar("No se encontró texto en la consola")
			return
		existente = self._registro.obtener(identidad)
		if existente is not None:
			self._registro.liberar_reserva(identidad, gestor)
			existente.activar()
			return
		visor = None
		try:
			from .interfaz.visor import VisorConsola

			self.vigilar_regiones(getattr(captura, "sin_filtrar", texto), anunciar=False)
			visor = VisorConsola(self, texto, destino, identidad, gestor, etiqueta_consola(destino, identidad))
			if not self._registro.registrar(identidad, visor):
				visor.cerrar_desde_complemento()
				return
			visor.mostrar()
		except Exception:
			log.exception("consoleLog: error al abrir el visor")
			self._registro.liberar_reserva(identidad, gestor)
			if visor is not None:
				self._registro.retirar(identidad, visor)
				try:
					visor.cerrar_desde_complemento()
				except Exception:
					pass
			avisos.anunciar("No se pudo abrir el visor de consola.")

	def _error_visor(self, identidad, gestor, error: str) -> None:
		self._registro.liberar_reserva(identidad, gestor)
		avisos.anunciar(error)

	def desregistrar_visor(self, identidad, visor) -> None:
		self._registro.retirar(identidad, visor)

	@property
	def registro(self) -> RegistroVisores:
		return self._registro

	# ------------------------------------------------------------------ copia rápida
	@script(description="Copia el contenido completo de la consola al portapapeles (rápido)", category=cfg.CATEGORIA)
	def script_copiarSalidaRapida(self, gesture) -> None:
		if self._bloqueada():
			return
		destino = self.destino_actual()
		if not es_ventana_consola(destino):
			avisos.anunciar("Esta no es una ventana de consola.")
			return
		self.copiar_consola(destino)

	def copiar_consola(self, destino: DestinoConsola) -> bool:
		def exito(captura) -> None:
			from .herramientas.copiar_salida import copiar

			texto = getattr(captura, "texto", captura) or ""
			h = self.herramientas.obtener_plugin("copiar_salida")
			ok = h.ejecutar(texto=texto) if h is not None else copiar(texto)
			avisos.anunciar("Contenido de consola copiado" if ok else "Error al copiar el contenido")

		iniciada = self._lector_copia.leer_consola(destino, exito, avisos.anunciar, emitir_beep=True, procesar=self.preparador(destino))
		if not iniciada:
			avisos.anunciar("Ya se está leyendo la consola.")
		return iniciada

	# ------------------------------------------------------------------ clic derecho
	@script(description="Pega el contenido del portapapeles mediante clic derecho en la consola enfocada", category=cfg.CATEGORIA)
	def script_clicDerechoConsola(self, gesture) -> None:
		if self._bloqueada():
			return
		destino = self.destino_actual()
		if not es_ventana_consola(destino):
			avisos.anunciar("La ventana enfocada no es una consola.")
			return
		h = self.herramientas.obtener_plugin("clic_derecho")
		if h is not None:
			h.ejecutar(destino=destino, tipo_consola=destino.tipo)
		else:
			from .herramientas.clic_derecho import clic_derecho_en_ventana

			clic_derecho_en_ventana(destino.hwnd)

	# ------------------------------------------------------------------ lanzador
	@script(description="Abre el lanzador de consolas de Windows", category=cfg.CATEGORIA)
	def script_abrirLanzador(self, gesture) -> None:
		if self._bloqueada():
			return
		if self._lanzador_abierto:
			avisos.anunciar("Ya hay una instancia del lanzador de consolas abierta.")
			return
		from tiresias import api

		primerPlano = api.getForegroundObject()
		foco = api.getFocusObject()
		try:
			app = primerPlano.appModule
			esExplorador = bool(app and str(app.appName).lower() == "explorer")
		except Exception:
			esExplorador = False
		try:
			hwnd = int(primerPlano.windowHandle or 0)
		except Exception:
			hwnd = 0
		try:
			nombreFoco = str(foco.name or "") if foco is not None else ""
		except Exception:
			nombreFoco = ""
		self._lanzador_abierto = True
		if not self.lanzador.detectadas:
			avisos.anunciar("Buscando las consolas instaladas...")
		from tiresias.gui.helpers import runOnGui

		self.lanzador.detectar_en_segundo_plano(lambda: runOnGui(self._mostrar_lanzador, esExplorador, hwnd, nombreFoco))

	def _mostrar_lanzador(self, esExplorador: bool, hwnd: int, nombreFoco: str) -> None:
		try:
			directorio = self.lanzador.obtener_directorio(esExplorador, hwnd, nombreFoco)
			if not directorio:
				avisos.anunciar("No se encontró una selección válida.")
				return
			from tiresias import gui

			from .interfaz.lanzador_dialogo import LanzadorDialogo

			marco = gui.mainFrame
			if marco is not None:
				marco.prePopup()
			try:
				dlg = LanzadorDialogo(marco, self.lanzador, directorio)
				try:
					dlg.Raise()
					dlg.ShowModal()
				finally:
					dlg.Destroy()
			finally:
				if marco is not None:
					marco.postPopup()
		except Exception:
			log.exception("consoleLog: error en el lanzador de consolas")
			avisos.anunciar("No se pudo abrir el lanzador de consolas.")
		finally:
			self._lanzador_abierto = False

	# ------------------------------------------------------------------ opciones
	def aplicar_configuracion(self, claves: set | None = None) -> None:
		"""Aplica las opciones guardadas (herramientas, protección y visores abiertos)."""
		self.herramientas.sincronizar(cfg.herramientasHabilitadas())
		if cfg.valor("proteccionRafagas"):
			self.protector.instalar()
		else:
			self.protector.desinstalar()
		cfg.migrarModelo()
		for visor in self._registro.visores():
			try:
				visor.aplicar_cambios()
			except Exception:
				log.debug("consoleLog: no se pudo actualizar un visor", exc_info=True)


GlobalPlugin = _Base if _modoSeguro() else ComplementoConsoleLog
