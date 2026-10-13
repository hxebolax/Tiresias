"""Gráficos de Office (Excel, Word y PowerPoint): lectura y navegación.

Los tres programas comparten el modelo de objetos de los gráficos
(``Chart``). :func:`readChart` lo convierte, en el hilo de Office, en un
diccionario de Python con el título, el tipo, los ejes, la leyenda y las
series con sus puntos. Después :class:`ChartNavigator` permite recorrerlo
sin volver a consultar a Office:

- Flecha derecha e izquierda: punto siguiente y anterior de la serie, con su
  categoría y su valor y un tono proporcional al valor.
- Flecha abajo y arriba: serie siguiente y anterior.
- Inicio y Fin: primer y último punto.
- Espacio: recorre la serie entera con tonos.
- Intro: resumen (título, tipo, ejes y leyenda). T: título; E: ejes;
  L: leyenda.
- Escape: sale de la navegación del gráfico.

Mientras la navegación está activa, estas teclas se asocian al módulo de la
aplicación (gestos de instancia) y no llegan al programa.
"""

from __future__ import annotations

import math
from typing import Any

from ..i18n import _

# Constantes del modelo de objetos (XlAxisType / XlChartType).
xlCategory = 1
xlValue = 2

CHART_TYPES = {
	1: _("de áreas"),
	4: _("de líneas"),
	5: _("circular"),
	15: _("de burbujas"),
	51: _("de columnas"),
	52: _("de columnas apiladas"),
	53: _("de columnas apiladas al cien por cien"),
	54: _("de columnas 3D"),
	57: _("de barras"),
	58: _("de barras apiladas"),
	59: _("de barras apiladas al cien por cien"),
	63: _("de líneas apiladas"),
	65: _("de líneas con marcadores"),
	69: _("circular seccionado"),
	76: _("de áreas apiladas"),
	-4100: _("de columnas 3D"),
	-4101: _("de líneas 3D"),
	-4102: _("circular 3D"),
	-4120: _("de anillo"),
	-4151: _("radial"),
	-4169: _("de dispersión"),
}

#: Tipos en los que la leyenda muestra categorías, no series.
_PIE_TYPES = {5, 69, -4102, -4120}

#: Límite de puntos por serie que se leen.
MAX_POINTS = 2000
#: Tonos: frecuencia mínima y máxima (escala logarítmica).
TONE_LOW = 220.0
TONE_HIGH = 1760.0


def _num(v: Any) -> float | None:
	try:
		f = float(v)
	except (TypeError, ValueError):
		return None
	if math.isnan(f) or math.isinf(f):
		return None
	return f


def _text(v: Any) -> str:
	if v is None:
		return ""
	if isinstance(v, float) and v.is_integer():
		return str(int(v))
	return str(v)


def formatNumber(v: float | None) -> str:
	if v is None:
		return _("sin valor")
	if float(v).is_integer():
		return str(int(v))
	return f"{v:.4g}".replace(".", ",")


# ================================================================ lectura (hilo de Office)
def readChart(chart) -> dict:
	"""Datos del gráfico ``chart`` (objeto COM) como diccionario de Python."""
	data: dict = {"title": "", "type": 0, "typeName": "", "axes": {}, "legend": [], "series": []}
	try:
		if chart.HasTitle:
			data["title"] = chart.ChartTitle.Text or ""
	except Exception:
		pass
	try:
		data["type"] = int(chart.ChartType)
	except Exception:
		pass
	data["typeName"] = CHART_TYPES.get(data["type"], "")
	for key, axisType in (("category", xlCategory), ("value", xlValue)):
		axis: dict = {}
		try:
			ax = chart.Axes(axisType)
		except Exception:
			continue
		try:
			if ax.HasTitle:
				axis["title"] = ax.AxisTitle.Text or ""
		except Exception:
			pass
		if key == "value":
			for attr, name in (("MinimumScale", "min"), ("MaximumScale", "max")):
				try:
					axis[name] = _num(getattr(ax, attr))
				except Exception:
					pass
		data["axes"][key] = axis
	coll = chart.SeriesCollection()
	for i in range(1, min(int(coll.Count), 50) + 1):
		s = coll.Item(i)
		try:
			values = list(s.Values or ())[:MAX_POINTS]
		except Exception:
			values = []
		try:
			cats = list(s.XValues or ())[:MAX_POINTS]
		except Exception:
			cats = []
		try:
			name = s.Name or ""
		except Exception:
			name = ""
		data["series"].append({"name": name, "values": [_num(v) for v in values], "categories": [_text(c) for c in cats]})
	hasLegend = False
	try:
		hasLegend = bool(chart.HasLegend)
	except Exception:
		pass
	if hasLegend:
		if data["type"] in _PIE_TYPES and data["series"]:
			data["legend"] = list(data["series"][0]["categories"])
		else:
			data["legend"] = [s["name"] for s in data["series"]]
	return data


# ================================================================ presentación
def summaryText(data: dict) -> str:
	parts = [_("Gráfico {kind}").format(kind=data.get("typeName") or "").strip()]
	parts.append(data.get("title") or _("sin título"))
	n = len(data.get("series") or [])
	parts.append(_("1 serie") if n == 1 else _("{n} series").format(n=n))
	parts.append(axesText(data))
	if data.get("legend"):
		parts.append(legendText(data))
	return ". ".join(p for p in parts if p)


def axesText(data: dict) -> str:
	axes = data.get("axes") or {}
	parts = []
	cat = axes.get("category") or {}
	val = axes.get("value") or {}
	if cat.get("title"):
		parts.append(_("eje de categorías: {t}").format(t=cat["title"]))
	if val or val.get("title"):
		text = _("eje de valores: {t}").format(t=val.get("title")) if val.get("title") else _("eje de valores")
		if val.get("min") is not None and val.get("max") is not None:
			text += ", " + _("de {a} a {b}").format(a=formatNumber(val["min"]), b=formatNumber(val["max"]))
		parts.append(text)
	return ", ".join(parts) if parts else _("sin ejes")


def legendText(data: dict) -> str:
	legend = data.get("legend") or []
	if not legend:
		return _("sin leyenda")
	return _("leyenda: {items}").format(items=", ".join(legend))


def valueRange(data: dict) -> tuple[float, float]:
	"""Mínimo y máximo de todos los valores (o la escala del eje)."""
	vals = [v for s in data.get("series") or [] for v in s.get("values") or [] if v is not None]
	lo = min(vals) if vals else 0.0
	hi = max(vals) if vals else 1.0
	axis = (data.get("axes") or {}).get("value") or {}
	if axis.get("min") is not None:
		lo = min(lo, axis["min"])
	if axis.get("max") is not None:
		hi = max(hi, axis["max"])
	return lo, hi


def toneFor(value: float | None, lo: float, hi: float) -> float | None:
	"""Frecuencia proporcional al valor (escala logarítmica entre dos octavas largas)."""
	if value is None:
		return None
	if hi <= lo:
		return math.sqrt(TONE_LOW * TONE_HIGH)
	ratio = max(0.0, min(1.0, (value - lo) / (hi - lo)))
	return TONE_LOW * (TONE_HIGH / TONE_LOW) ** ratio


class ChartNavigator:
	"""Recorrido de un gráfico ya leído (sin acceso a Office)."""

	def __init__(self, data: dict) -> None:
		self.data = data
		self.series = 0
		self.point = 0
		self.lo, self.hi = valueRange(data)

	@property
	def currentSeries(self) -> dict | None:
		ss = self.data.get("series") or []
		return ss[self.series] if 0 <= self.series < len(ss) else None

	def pointCount(self) -> int:
		s = self.currentSeries
		return len(s["values"]) if s else 0

	def pointText(self) -> str:
		s = self.currentSeries
		if s is None or not s["values"]:
			return _("Serie sin puntos")
		value = s["values"][self.point]
		cats = s.get("categories") or []
		cat = cats[self.point] if self.point < len(cats) and cats[self.point] else str(self.point + 1)
		return _("{cat}: {value}, punto {n} de {total}").format(cat=cat, value=formatNumber(value), n=self.point + 1, total=len(s["values"]))

	def seriesText(self) -> str:
		s = self.currentSeries
		if s is None:
			return _("Sin series")
		total = len(self.data.get("series") or [])
		name = s.get("name") or _("sin nombre")
		return _("Serie {name}, {n} de {total}, {points} puntos").format(name=name, n=self.series + 1, total=total, points=len(s["values"]))

	def currentTone(self) -> float | None:
		s = self.currentSeries
		if s is None or not s["values"]:
			return None
		return toneFor(s["values"][self.point], self.lo, self.hi)

	def movePoint(self, delta: int) -> bool:
		n = self.pointCount()
		new = self.point + delta
		if n == 0 or new < 0 or new >= n:
			return False
		self.point = new
		return True

	def moveToEdge(self, last: bool) -> bool:
		n = self.pointCount()
		if n == 0:
			return False
		self.point = n - 1 if last else 0
		return True

	def moveSeries(self, delta: int) -> bool:
		total = len(self.data.get("series") or [])
		new = self.series + delta
		if new < 0 or new >= total:
			return False
		self.series = new
		self.point = min(self.point, max(0, self.pointCount() - 1))
		return True

	def seriesTones(self) -> list[float | None]:
		s = self.currentSeries
		if s is None:
			return []
		return [toneFor(v, self.lo, self.hi) for v in s["values"]]


# ================================================================ obtener el gráfico en cada aplicación
def om_excelChart(hwnd: int) -> dict | None:
	"""Gráfico activo de Excel o, si la hoja tiene uno solo, ese."""
	from . import _office

	app = _office.nativeOMFromWindow(hwnd).Application
	chart = app.ActiveChart
	if chart is None:
		try:
			objs = app.ActiveSheet.ChartObjects()
			if int(objs.Count) == 1:
				chart = objs.Item(1).Chart
		except Exception:
			chart = None
	return readChart(chart) if chart is not None else None


def om_wordChart(hwnd: int) -> dict | None:
	"""Gráfico seleccionado en Word o el primero del párrafo del cursor."""
	from . import _office

	sel = _office.nativeOMFromWindow(hwnd).Application.Selection
	candidates = []
	for getter in (lambda: sel.InlineShapes, lambda: sel.ShapeRange, lambda: sel.Paragraphs(1).Range.InlineShapes):
		try:
			coll = getter()
			for i in range(1, int(coll.Count) + 1):
				candidates.append(coll.Item(i))
		except Exception:
			continue
	for shape in candidates:
		try:
			if shape.HasChart:
				return readChart(shape.Chart)
		except Exception:
			continue
	return None


def om_pptChart(hwnd: int) -> dict | None:
	"""Gráfico seleccionado en PowerPoint o el primero de la diapositiva actual."""
	from . import _office

	app = _office.nativeOMFromWindow(hwnd).Application
	shapes = []
	try:
		rng = app.ActiveWindow.Selection.ShapeRange
		shapes.extend(rng.Item(i) for i in range(1, int(rng.Count) + 1))
	except Exception:
		pass
	try:
		slide = app.ActiveWindow.View.Slide
		shapes.extend(slide.Shapes.Item(i) for i in range(1, int(slide.Shapes.Count) + 1))
	except Exception:
		pass
	for shape in shapes:
		try:
			if shape.HasChart:
				return readChart(shape.Chart)
		except Exception:
			continue
	return None


def fullText(data: dict) -> str:
	"""El gráfico entero como texto (para la ventana navegable)."""
	lines = [summaryText(data)]
	for s in data.get("series") or []:
		lines.append("")
		lines.append(_("Serie {name}").format(name=s.get("name") or _("sin nombre")))
		cats = s.get("categories") or []
		for i, v in enumerate(s.get("values") or []):
			label = cats[i] if i < len(cats) and cats[i] else str(i + 1)
			lines.append(f"  {label}: {formatNumber(v)}")
	return "\n".join(lines)


# ================================================================ navegación en el módulo de la aplicación
#: Tecla -> orden mientras se navega por un gráfico.
NAV_GESTURES = {
	"kb:rightArrow": "chart_nextPoint",
	"kb:leftArrow": "chart_previousPoint",
	"kb:downArrow": "chart_nextSeries",
	"kb:upArrow": "chart_previousSeries",
	"kb:home": "chart_firstPoint",
	"kb:end": "chart_lastPoint",
	"kb:space": "chart_playSeries",
	"kb:enter": "chart_summary",
	"kb:t": "chart_title",
	"kb:e": "chart_axes",
	"kb:l": "chart_legend",
	"kb:escape": "chart_exit",
}


class ChartNavigationMixin:
	"""Añade la navegación por gráficos a un módulo de aplicación."""

	chartNavigator: ChartNavigator | None = None

	def startChartNavigation(self, data: dict) -> None:
		from .. import api, speech
		from ..baseobject import normalizeGestureId

		self.stopChartNavigation(silent=True)
		self.chartNavigator = ChartNavigator(data)
		inst = self.__dict__.setdefault("_instanceGestures", {})
		for g, name in NAV_GESTURES.items():
			inst[normalizeGestureId(g)] = name
		api.post_focusChange.register(self._chartFocusChanged)
		speech.cancelSpeech()
		speech.speakText(summaryText(data) + ". " + self.chartNavigator.seriesText() + ". " + _("Flechas para recorrerlo, Escape para salir"))

	def stopChartNavigation(self, silent: bool = False) -> None:
		from .. import api, speech
		from ..baseobject import normalizeGestureId

		if self.chartNavigator is None:
			return
		self.chartNavigator = None
		inst = self.__dict__.get("_instanceGestures") or {}
		for g in NAV_GESTURES:
			inst.pop(normalizeGestureId(g), None)
		try:
			api.post_focusChange.unregister(self._chartFocusChanged)
		except Exception:
			pass
		if not silent:
			speech.speakMessage(_("Fuera del gráfico"))

	def _chartFocusChanged(self, obj=None) -> None:
		from .. import queue_handler

		queue_handler.queueFunction(self.stopChartNavigation, True)

	def _chartSpeak(self, moved: bool, text: str, tone: bool = True) -> None:
		from .. import speech
		from ..audio import tones
		from ..config import conf

		if not moved:
			tones.playSound("boundary")
			return
		speech.cancelSpeech()
		nav = self.chartNavigator
		if tone and nav is not None and conf["charts"]["pointTones"]:
			hz = nav.currentTone()
			if hz:
				tones.beep(hz, int(conf["charts"]["toneDuration"]), interrupt=True)
		speech.speakText(text)

	def script_chart_nextPoint(self, gesture) -> None:
		nav = self.chartNavigator
		if nav is not None:
			self._chartSpeak(nav.movePoint(1), nav.pointText())

	def script_chart_previousPoint(self, gesture) -> None:
		nav = self.chartNavigator
		if nav is not None:
			self._chartSpeak(nav.movePoint(-1), nav.pointText())

	def script_chart_firstPoint(self, gesture) -> None:
		nav = self.chartNavigator
		if nav is not None:
			self._chartSpeak(nav.moveToEdge(False), nav.pointText())

	def script_chart_lastPoint(self, gesture) -> None:
		nav = self.chartNavigator
		if nav is not None:
			self._chartSpeak(nav.moveToEdge(True), nav.pointText())

	def script_chart_nextSeries(self, gesture) -> None:
		nav = self.chartNavigator
		if nav is not None:
			self._chartSpeak(nav.moveSeries(1), nav.seriesText() + ". " + nav.pointText())

	def script_chart_previousSeries(self, gesture) -> None:
		nav = self.chartNavigator
		if nav is not None:
			self._chartSpeak(nav.moveSeries(-1), nav.seriesText() + ". " + nav.pointText())

	def script_chart_playSeries(self, gesture) -> None:
		from .. import speech
		from ..audio import tones
		from ..config import conf

		nav = self.chartNavigator
		if nav is None:
			return
		speech.cancelSpeech()
		duration = int(conf["charts"]["toneDuration"])
		first = True
		for hz in nav.seriesTones():
			if hz is None:
				continue
			tones.beep(hz, duration, interrupt=first)
			first = False

	def script_chart_summary(self, gesture) -> None:
		from .. import speech

		if self.chartNavigator is not None:
			speech.cancelSpeech()
			speech.speakText(summaryText(self.chartNavigator.data))

	def script_chart_title(self, gesture) -> None:
		from .. import speech

		if self.chartNavigator is not None:
			speech.speakText(self.chartNavigator.data.get("title") or _("sin título"))

	def script_chart_axes(self, gesture) -> None:
		from .. import speech

		if self.chartNavigator is not None:
			speech.speakText(axesText(self.chartNavigator.data))

	def script_chart_legend(self, gesture) -> None:
		from .. import speech

		if self.chartNavigator is not None:
			speech.speakText(legendText(self.chartNavigator.data))

	def script_chart_exit(self, gesture) -> None:
		self.stopChartNavigation()

	def openChart(self, omFunc, hwnd: int) -> None:
		"""Lee el gráfico con ``omFunc`` y empieza a navegar (dos veces: lo muestra entero)."""
		from .. import speech
		from ..input import core as inputCore
		from . import _office

		show = inputCore.getLastScriptRepeatCount() == 1

		def done(data) -> None:
			if not data:
				speech.speakMessage(_("No hay ningún gráfico seleccionado"))
				return
			if show:
				from .. import gui

				self.stopChartNavigation(silent=True)
				gui.showBrowseableMessage(fullText(data), _("Gráfico"))
				return
			self.startChartNavigation(data)

		_office.callAsync(omFunc, hwnd, callback=done, onError=lambda e: speech.speakMessage(_office.busyMessage(e)), timeout=5)


for _name in set(NAV_GESTURES.values()):
	_f = getattr(ChartNavigationMixin, "script_" + _name)
	_f.category = _("Gráficos de Office")  # type: ignore[attr-defined]
ChartNavigationMixin.script_chart_nextPoint.__doc__ = _("Gráfico: punto siguiente")
ChartNavigationMixin.script_chart_previousPoint.__doc__ = _("Gráfico: punto anterior")
ChartNavigationMixin.script_chart_firstPoint.__doc__ = _("Gráfico: primer punto")
ChartNavigationMixin.script_chart_lastPoint.__doc__ = _("Gráfico: último punto")
ChartNavigationMixin.script_chart_nextSeries.__doc__ = _("Gráfico: serie siguiente")
ChartNavigationMixin.script_chart_previousSeries.__doc__ = _("Gráfico: serie anterior")
ChartNavigationMixin.script_chart_playSeries.__doc__ = _("Gráfico: recorre la serie entera con tonos")
ChartNavigationMixin.script_chart_summary.__doc__ = _("Gráfico: resumen")
ChartNavigationMixin.script_chart_title.__doc__ = _("Gráfico: título")
ChartNavigationMixin.script_chart_axes.__doc__ = _("Gráfico: ejes")
ChartNavigationMixin.script_chart_legend.__doc__ = _("Gráfico: leyenda")
ChartNavigationMixin.script_chart_exit.__doc__ = _("Gráfico: salir de la navegación")
