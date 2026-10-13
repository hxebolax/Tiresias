"""Procesamiento avanzado del texto de las consolas (código propio, sin dependencias).

- Limpieza y análisis de secuencias de escape ANSI (8, 16, 256 colores y RGB,
  negrita, cursiva, subrayado, parpadeo, inverso, oculto y tachado).
- Ancho de visualización Unicode (caracteres CJK anchos y combinantes).
- Texto bidireccional (árabe, hebreo...): detección y reordenación visual.
- Secuencias de emoji (ZWJ, tonos de piel, selectores de variación, banderas).
- Indentación de líneas, condensación de símbolos repetidos y niveles de
  puntuación.

Inspirado en las utilidades de «Terminal Access for NVDA» que incorporaba el
complemento original.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

NIVEL_PUNT_NINGUNO = 0
NIVEL_PUNT_ALGUNO = 1
NIVEL_PUNT_MAYORIA = 2
NIVEL_PUNT_TODO = 3

CONJUNTOS_PUNTUACION: dict[int, set | None] = {
	NIVEL_PUNT_NINGUNO: set(),
	NIVEL_PUNT_ALGUNO: set(".,?!;:"),
	NIVEL_PUNT_MAYORIA: set(".,?!;:@#$%^&*()_+=[]{}\\|<>/"),
	NIVEL_PUNT_TODO: None,
}

SIMBOLOS_CONDENSAR_DEFECTO = "-_=!"

_RANGOS_RTL = (
	(0x0590, 0x05FF),  # hebreo
	(0x0600, 0x06FF),  # árabe
	(0x0700, 0x074F),  # siríaco
	(0x0750, 0x077F),  # árabe suplemento
	(0x0780, 0x07BF),  # thaana
	(0x07C0, 0x07FF),  # NKo
	(0x0800, 0x083F),  # samaritano
	(0x0840, 0x085F),  # mandeo
	(0x08A0, 0x08FF),  # árabe extendido A
	(0xFB1D, 0xFB4F),  # formas de presentación hebreas
	(0xFB50, 0xFDFF),  # formas de presentación árabes A
	(0xFE70, 0xFEFF),  # formas de presentación árabes B
)


def _esRtl(caracter: str) -> bool:
	codigo = ord(caracter)
	for inicio, fin in _RANGOS_RTL:
		if inicio <= codigo <= fin:
			return True
	return False


# ====================================================================== ANSI
class AnalizadorANSI:
	"""Analizador de secuencias SGR (``ESC[...m``) y limpiador de escapes."""

	COLORES_TEXTO = {
		30: "negro", 31: "rojo", 32: "verde", 33: "amarillo",
		34: "azul", 35: "magenta", 36: "cian", 37: "blanco",
		90: "negro brillante", 91: "rojo brillante",
		92: "verde brillante", 93: "amarillo brillante",
		94: "azul brillante", 95: "magenta brillante",
		96: "cian brillante", 97: "blanco brillante",
	}
	COLORES_FONDO = {
		40: "negro", 41: "rojo", 42: "verde", 43: "amarillo",
		44: "azul", 45: "magenta", 46: "cian", 47: "blanco",
		100: "negro brillante", 101: "rojo brillante",
		102: "verde brillante", 103: "amarillo brillante",
		104: "azul brillante", 105: "magenta brillante",
		106: "cian brillante", 107: "blanco brillante",
	}
	CODIGOS_FORMATO = {
		1: "negrita", 2: "tenue", 3: "cursiva", 4: "subrayado",
		5: "parpadeo lento", 6: "parpadeo rápido", 7: "inverso",
		8: "oculto", 9: "tachado",
	}
	#: CSI (``ESC[...letra``), OSC (``ESC]...BEL`` o ``ESC]...ESC\\``) y escapes de dos caracteres.
	_PATRON_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")
	_PATRON_SGR = re.compile(r"\x1b\[([0-9;]*)m")

	def __init__(self) -> None:
		self.reiniciar()

	def reiniciar(self) -> None:
		self.color_texto: Any = None
		self.color_fondo: Any = None
		self.negrita = False
		self.tenue = False
		self.cursiva = False
		self.subrayado = False
		self.parpadeo = False
		self.inverso = False
		self.oculto = False
		self.tachado = False

	def analizar(self, texto: str) -> dict:
		for coincidencia in self._PATRON_SGR.findall(texto or ""):
			codigos = [int(c) for c in coincidencia.split(";") if c.isdigit()]
			self._procesar_codigos(codigos or [0])
		return self._obtener_atributos()

	def _procesar_codigos(self, codigos: list[int]) -> None:
		i = 0
		while i < len(codigos):
			codigo = codigos[i]
			if codigo == 0:
				self.reiniciar()
			elif codigo in self.COLORES_TEXTO:
				self.color_texto = self.COLORES_TEXTO[codigo]
			elif codigo in self.COLORES_FONDO:
				self.color_fondo = self.COLORES_FONDO[codigo]
			elif codigo in self.CODIGOS_FORMATO:
				attr = self.CODIGOS_FORMATO[codigo]
				if attr == "negrita":
					self.negrita = True
				elif attr == "tenue":
					self.tenue = True
				elif attr == "cursiva":
					self.cursiva = True
				elif attr == "subrayado":
					self.subrayado = True
				elif attr in ("parpadeo lento", "parpadeo rápido"):
					self.parpadeo = True
				elif attr == "inverso":
					self.inverso = True
				elif attr == "oculto":
					self.oculto = True
				elif attr == "tachado":
					self.tachado = True
			elif codigo == 22:
				self.negrita = False
				self.tenue = False
			elif codigo == 23:
				self.cursiva = False
			elif codigo == 24:
				self.subrayado = False
			elif codigo == 25:
				self.parpadeo = False
			elif codigo == 27:
				self.inverso = False
			elif codigo == 28:
				self.oculto = False
			elif codigo == 29:
				self.tachado = False
			elif codigo in (38, 48) and i + 2 < len(codigos) and codigos[i + 1] == 5:
				valor = "color{}".format(codigos[i + 2])
				if codigo == 38:
					self.color_texto = valor
				else:
					self.color_fondo = valor
				i += 2
			elif codigo in (38, 48) and i + 4 < len(codigos) and codigos[i + 1] == 2:
				valor = (codigos[i + 2], codigos[i + 3], codigos[i + 4])
				if codigo == 38:
					self.color_texto = valor
				else:
					self.color_fondo = valor
				i += 4
			elif codigo == 39:
				self.color_texto = None
			elif codigo == 49:
				self.color_fondo = None
			i += 1

	def _obtener_atributos(self) -> dict:
		return {
			"color_texto": self.color_texto,
			"color_fondo": self.color_fondo,
			"negrita": self.negrita,
			"tenue": self.tenue,
			"cursiva": self.cursiva,
			"subrayado": self.subrayado,
			"parpadeo": self.parpadeo,
			"inverso": self.inverso,
			"oculto": self.oculto,
			"tachado": self.tachado,
		}

	def formatear_atributos(self, modo: str = "detallado") -> str:
		a = self._obtener_atributos()
		partes: list[str] = []
		if modo == "breve":
			if a["color_texto"]:
				partes.append("color RGB" if isinstance(a["color_texto"], tuple) else str(a["color_texto"]))
			if a["color_fondo"]:
				partes.append("fondo RGB" if isinstance(a["color_fondo"], tuple) else "fondo {}".format(a["color_fondo"]))
		else:
			if a["color_texto"]:
				if isinstance(a["color_texto"], tuple):
					partes.append("texto RGB({},{},{})".format(*a["color_texto"]))
				else:
					partes.append("texto {}".format(a["color_texto"]))
			if a["color_fondo"]:
				if isinstance(a["color_fondo"], tuple):
					partes.append("fondo RGB({},{},{})".format(*a["color_fondo"]))
				else:
					partes.append("fondo {}".format(a["color_fondo"]))
			formatos = [nombre for clave, nombre in (
				("negrita", "negrita"), ("tenue", "tenue"), ("cursiva", "cursiva"),
				("subrayado", "subrayado"), ("parpadeo", "parpadeo"), ("inverso", "inverso"),
				("oculto", "oculto"), ("tachado", "tachado"),
			) if a[clave]]
			if formatos:
				partes.append(", ".join(formatos))
		return ", ".join(partes) if partes else "atributos por defecto"

	@classmethod
	def limpiar_ansi(cls, texto: str) -> str:
		return cls._PATRON_ANSI.sub("", texto or "")


# ====================================================================== Unicode
class AyudanteUnicode:
	"""Ancho de visualización: CJK = 2 columnas, combinantes = 0, resto = 1."""

	@staticmethod
	def obtener_ancho_caracter(caracter: str) -> int:
		if not caracter:
			return 0
		try:
			if unicodedata.combining(caracter) or unicodedata.category(caracter) in ("Mn", "Me", "Cf"):
				return 0
			if ord(caracter) < 32 or 0x7F <= ord(caracter) < 0xA0:
				return 0
			if unicodedata.east_asian_width(caracter) in ("W", "F"):
				return 2
		except (TypeError, ValueError):
			return 1
		return 1

	@classmethod
	def obtener_ancho_texto(cls, texto: str) -> int:
		return sum(cls.obtener_ancho_caracter(c) for c in texto or "")

	@classmethod
	def extraer_rango_columnas(cls, texto: str, col_inicio: int, col_fin: int) -> str:
		"""Texto entre dos columnas (base 1, inclusivas) según el ancho visual."""
		if not texto:
			return ""
		resultado = []
		col_actual = 1
		for caracter in texto:
			ancho = cls.obtener_ancho_caracter(caracter)
			col_fin_caracter = col_actual + max(ancho, 1) - 1
			if col_actual > col_fin:
				break
			if col_fin_caracter >= col_inicio:
				resultado.append(caracter)
			col_actual += ancho
		return "".join(resultado)


# ====================================================================== bidireccional
class AyudanteBidi:
	"""Texto bidireccional: detección de dirección y reordenación visual propia.

	La reordenación es una versión simplificada del algoritmo UAX #9 pensada
	para líneas de consola: en una línea de dirección derecha a izquierda se
	invierte el orden de los tramos y el de los caracteres de cada tramo RTL,
	conservando los números y las palabras latinas en su orden de lectura.
	"""

	disponible = True
	reshaper_disponible = False

	def es_rtl(self, texto: str) -> bool:
		rtl = ltr = 0
		for c in texto or "":
			if _esRtl(c):
				rtl += 1
			elif c.isalpha():
				ltr += 1
		return rtl > ltr

	def detectar_direccion(self, texto: str) -> str:
		rtl = ltr = 0
		for c in texto or "":
			if _esRtl(c):
				rtl += 1
			elif c.isalpha():
				ltr += 1
		total = rtl + ltr
		if not total:
			return "ltr"
		ratio = rtl / total
		if ratio > 0.6:
			return "rtl"
		if ratio > 0.3:
			return "mixto"
		return "ltr"

	@staticmethod
	def _tramos(linea: str) -> list[tuple[bool, str]]:
		"""Divide la línea en tramos RTL y no RTL (los neutros se unen al anterior)."""
		tramos: list[list] = []
		for c in linea:
			rtl = _esRtl(c)
			neutro = not c.isalnum() and not rtl
			if tramos and (neutro or tramos[-1][0] == rtl):
				tramos[-1][1].append(c)
			else:
				tramos.append([rtl, [c]])
		return [(t[0], "".join(t[1])) for t in tramos]

	def procesar_texto(self, texto: str) -> str:
		if not texto or not self.es_rtl(texto):
			return texto
		salida = []
		for rtl, tramo in reversed(self._tramos(texto)):
			salida.append(tramo[::-1] if rtl else tramo)
		return "".join(salida)

	def procesar_linea_a_linea(self, texto: str) -> str:
		if not texto:
			return texto
		resultado = []
		for linea in texto.splitlines(keepends=True):
			fin = ""
			cuerpo = linea
			while cuerpo.endswith(("\n", "\r")):
				fin = cuerpo[-1] + fin
				cuerpo = cuerpo[:-1]
			resultado.append((self.procesar_texto(cuerpo) if self.es_rtl(cuerpo) else cuerpo) + fin)
		return "".join(resultado)

	def extraer_rango_columnas_rtl(self, texto: str, col_inicio: int, col_fin: int) -> str:
		if not texto:
			return ""
		if self.es_rtl(texto):
			ancho = AyudanteUnicode.obtener_ancho_texto(texto)
			return AyudanteUnicode.extraer_rango_columnas(texto, ancho - col_fin + 1, ancho - col_inicio + 1)
		return AyudanteUnicode.extraer_rango_columnas(texto, col_inicio, col_fin)

	def obtener_info_direccion(self, texto: str) -> str:
		if not texto:
			return "texto vacío"
		direccion = self.detectar_direccion(texto)
		rtl = sum(1 for c in texto if c.isalpha() and _esRtl(c))
		ltr = sum(1 for c in texto if c.isalpha() and not _esRtl(c))
		partes = [{
			"rtl": "dirección: derecha a izquierda (RTL)",
			"mixto": "dirección: mixto RTL/LTR",
		}.get(direccion, "dirección: izquierda a derecha (LTR)")]
		if rtl:
			partes.append("{} caracteres RTL".format(rtl))
		if ltr:
			partes.append("{} caracteres LTR".format(ltr))
		partes.append("reordenación bidireccional: incorporada")
		return ", ".join(partes)


# ====================================================================== emoji
class AyudanteEmoji:
	"""Secuencias de emoji con detección heurística por rangos Unicode."""

	_RANGOS_EMOJI = (
		(0x1F600, 0x1F64F),
		(0x1F300, 0x1F5FF),
		(0x1F680, 0x1F6FF),
		(0x1F700, 0x1F77F),
		(0x1F900, 0x1F9FF),
		(0x1FA00, 0x1FA6F),
		(0x1FA70, 0x1FAFF),
		(0x2600, 0x26FF),
		(0x2700, 0x27BF),
		(0xFE00, 0xFE0F),
		(0x200D, 0x200D),
		(0x1F3FB, 0x1F3FF),
		(0x1F1E6, 0x1F1FF),  # indicadores regionales (banderas)
	)
	disponible = False

	def _esEmoji(self, caracter: str) -> bool:
		codigo = ord(caracter)
		for inicio, fin in self._RANGOS_EMOJI:
			if inicio <= codigo <= fin:
				return True
		return 0x1F000 <= codigo <= 0x1FFFF

	@staticmethod
	def _esContinuacion(codigo: int) -> bool:
		return codigo == 0x200D or 0xFE00 <= codigo <= 0xFE0F or 0x1F3FB <= codigo <= 0x1F3FF or 0xE0020 <= codigo <= 0xE007F

	def contiene_emoji(self, texto: str) -> bool:
		return any(self._esEmoji(c) for c in texto or "" if ord(c) not in (0x200D,) and not 0xFE00 <= ord(c) <= 0xFE0F)

	def extraer_lista_emoji(self, texto: str) -> list[str]:
		"""Emoji del texto; las secuencias (ZWJ, tonos, banderas) cuentan como uno."""
		emojis: list[str] = []
		i = 0
		texto = texto or ""
		while i < len(texto):
			c = texto[i]
			if self._esEmoji(c) and not self._esContinuacion(ord(c)):
				j = i + 1
				regional = 0x1F1E6 <= ord(c) <= 0x1F1FF
				if regional and j < len(texto) and 0x1F1E6 <= ord(texto[j]) <= 0x1F1FF:
					j += 1
				while j < len(texto):
					cod = ord(texto[j])
					if self._esContinuacion(cod):
						j += 1
						if cod == 0x200D and j < len(texto) and self._esEmoji(texto[j]):
							j += 1
						continue
					break
				emojis.append(texto[i:j])
				i = j
			else:
				i += 1
		return emojis

	def contar_emoji(self, texto: str) -> int:
		return len(self.extraer_lista_emoji(texto))

	def obtener_ancho_emoji(self, texto_emoji: str) -> int:
		if not texto_emoji:
			return 0
		lista = self.extraer_lista_emoji(texto_emoji)
		if lista:
			return len(lista) * 2
		return AyudanteUnicode.obtener_ancho_texto(texto_emoji)

	def obtener_ancho_texto_con_emoji(self, texto: str) -> int:
		if not texto:
			return 0
		total = 0
		i = 0
		while i < len(texto):
			c = texto[i]
			if self._esEmoji(c) and not self._esContinuacion(ord(c)):
				secuencia = self.extraer_lista_emoji(texto[i:])[0]
				total += 2
				i += len(secuencia)
			else:
				total += AyudanteUnicode.obtener_ancho_caracter(c)
				i += 1
		return total

	def obtener_descripcion_emoji(self, emoji: str) -> str:
		if not emoji:
			return ""
		nombres = []
		for c in emoji:
			if self._esContinuacion(ord(c)):
				continue
			try:
				nombre = unicodedata.name(c, "")
			except (TypeError, ValueError):
				nombre = ""
			if nombre:
				nombres.append(nombre.lower())
		return " + ".join(nombres) if nombres else emoji

	def obtener_info_emoji(self, texto: str) -> str:
		if not texto:
			return "texto vacío"
		emojis = self.extraer_lista_emoji(texto)
		if not emojis:
			return "no se encontraron emoji"
		cuenta = len(emojis)
		partes = ["{} emoji encontrado".format(cuenta) if cuenta == 1 else "{} emoji encontrados".format(cuenta)]
		for i, em in enumerate(emojis[:10], 1):
			partes.append("  {}: {} ({})".format(i, em, self.obtener_descripcion_emoji(em)))
		if cuenta > 10:
			partes.append("  ... y {} más".format(cuenta - 10))
		partes.append("detección de emoji: propia, por rangos Unicode")
		return "\n".join(partes)


# ====================================================================== indentación
class DetectorIndentacion:
	@staticmethod
	def detectar_indentacion(linea: str) -> str:
		if not linea or linea[0] not in (" ", "\t"):
			return "sin indentación"
		espacios = tabulaciones = 0
		for c in linea:
			if c == " ":
				espacios += 1
			elif c == "\t":
				tabulaciones += 1
			else:
				break
		partes = []
		if tabulaciones:
			partes.append("{} tabulación".format(tabulaciones) if tabulaciones == 1 else "{} tabulaciones".format(tabulaciones))
		if espacios:
			partes.append("{} espacio".format(espacios) if espacios == 1 else "{} espacios".format(espacios))
		return ", ".join(partes) if partes else "sin indentación"

	@staticmethod
	def obtener_nivel_indentacion(linea: str, tamano_tab: int = 4) -> int:
		nivel = 0
		for c in linea or "":
			if c == " ":
				nivel += 1
			elif c == "\t":
				nivel += tamano_tab
			else:
				break
		return nivel


# ====================================================================== símbolos y puntuación
class CondensadorSimbolos:
	"""``=====`` → «5 igual» (a partir de tres repeticiones)."""

	NOMBRES = {
		"-": "guión",
		"_": "guión bajo",
		"=": "igual",
		"!": "exclamación",
		"#": "almohadilla",
		"*": "asterisco",
		".": "punto",
		"+": "más",
		"~": "tilde",
		"^": "circunflejo",
	}

	def __init__(self, simbolos: str = SIMBOLOS_CONDENSAR_DEFECTO) -> None:
		self._simbolos = set(simbolos)

	@property
	def simbolos(self) -> str:
		return "".join(sorted(self._simbolos))

	@simbolos.setter
	def simbolos(self, valor: str) -> None:
		self._simbolos = set((valor or "")[:50])

	def condensar(self, texto: str) -> str:
		if not texto or not self._simbolos:
			return texto
		resultado = []
		i = 0
		n = len(texto)
		while i < n:
			c = texto[i]
			if c in self._simbolos:
				cuenta = 1
				while i + cuenta < n and texto[i + cuenta] == c:
					cuenta += 1
				if cuenta >= 3:
					resultado.append("{} {}".format(cuenta, self.NOMBRES.get(c, c)))
				else:
					resultado.append(c * cuenta)
				i += cuenta
			else:
				resultado.append(c)
				i += 1
		return "".join(resultado)


class FiltroPuntuacion:
	"""Deja solo la puntuación del nivel elegido (Ninguno, Alguno, Mayoría, Todo)."""

	NOMBRES = {
		NIVEL_PUNT_NINGUNO: "Ninguno",
		NIVEL_PUNT_ALGUNO: "Alguno",
		NIVEL_PUNT_MAYORIA: "Mayoría",
		NIVEL_PUNT_TODO: "Todo",
	}

	def __init__(self, nivel: int = NIVEL_PUNT_MAYORIA) -> None:
		self._nivel = max(0, min(3, int(nivel)))

	@property
	def nivel(self) -> int:
		return self._nivel

	@nivel.setter
	def nivel(self, valor: int) -> None:
		self._nivel = max(0, min(3, int(valor)))

	def nombre_nivel(self) -> str:
		return self.NOMBRES.get(self._nivel, "Desconocido")

	def filtrar(self, texto: str) -> str:
		if self._nivel == NIVEL_PUNT_TODO or not texto:
			return texto
		conjunto = CONJUNTOS_PUNTUACION.get(self._nivel) or set()
		return "".join(c for c in texto if c.isalnum() or c.isspace() or c in conjunto)


# ====================================================================== procesador
class ProcesadorTexto:
	"""Tubería: ANSI → bidireccional → condensación de símbolos."""

	def __init__(self) -> None:
		self._analizador_ansi = AnalizadorANSI()
		self._condensador = CondensadorSimbolos()
		self._filtro_puntuacion = FiltroPuntuacion()
		self._detector_indentacion = DetectorIndentacion()
		self._ayudante_bidi = AyudanteBidi()
		self._ayudante_emoji = AyudanteEmoji()

	@property
	def condensador(self) -> CondensadorSimbolos:
		return self._condensador

	@property
	def filtro_puntuacion(self) -> FiltroPuntuacion:
		return self._filtro_puntuacion

	@property
	def analizador_ansi(self) -> AnalizadorANSI:
		return self._analizador_ansi

	@property
	def ayudante_bidi(self) -> AyudanteBidi:
		return self._ayudante_bidi

	@property
	def ayudante_emoji(self) -> AyudanteEmoji:
		return self._ayudante_emoji

	def procesar_texto(
		self,
		texto: str,
		limpiar_ansi: bool = True,
		condensar_simbolos: bool = False,
		detectar_indentacion: bool = False,
		procesar_bidi: bool = False,
		procesar_emoji: bool = False,
		simbolos: str | None = None,
	) -> str:
		"""El emoji no cambia el texto: solo ajusta los cálculos de ancho."""
		if not texto:
			return texto
		resultado = texto
		if limpiar_ansi:
			resultado = AnalizadorANSI.limpiar_ansi(resultado)
		if procesar_bidi:
			resultado = self._ayudante_bidi.procesar_linea_a_linea(resultado)
		if condensar_simbolos:
			if simbolos is not None:
				condensador = CondensadorSimbolos(simbolos)
				resultado = condensador.condensar(resultado)
			else:
				resultado = self._condensador.condensar(resultado)
		return resultado

	def obtener_atributos_posicion(self, texto: str) -> str:
		self._analizador_ansi.reiniciar()
		self._analizador_ansi.analizar(texto)
		return self._analizador_ansi.formatear_atributos()

	def obtener_indentacion(self, linea: str) -> str:
		return self._detector_indentacion.detectar_indentacion(linea)

	def obtener_ancho_texto(self, texto: str) -> int:
		if self._ayudante_emoji.contiene_emoji(texto):
			return self._ayudante_emoji.obtener_ancho_texto_con_emoji(texto)
		return AyudanteUnicode.obtener_ancho_texto(texto)

	def obtener_info_texto(self, texto: str) -> str:
		if not texto:
			return "texto vacío"
		partes = ["=== Análisis de texto ===", "Dirección: {}".format(self._ayudante_bidi.obtener_info_direccion(texto))]
		if self._ayudante_emoji.contiene_emoji(texto):
			partes += ["", "Emoji:", self._ayudante_emoji.obtener_info_emoji(texto)]
		if "\x1b[" in texto:
			partes += ["", "Formato ANSI detectado"]
		partes += [
			"",
			"Ancho de visualización: {} columnas".format(self.obtener_ancho_texto(texto)),
			"Longitud: {} caracteres".format(len(texto)),
		]
		return "\n".join(partes)
