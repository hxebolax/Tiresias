"""Categoría «Matemáticas» del diálogo de opciones."""

from __future__ import annotations

from ..i18n import _


def registerPanel() -> None:
	from ..gui import settings

	class MathPanel(settings.ConfigPanel):
		title = _("Matemáticas")
		section = "math"
		fields = [
			settings.Choice(
				"verbosity",
				_("&Verbosidad de la lectura:"),
				[("breve", _("Breve")), ("normal", _("Normal")), ("detallado", _("Detallada"))],
			),
			settings.Choice(
				"style",
				_("&Estilo de lectura:"),
				[("natural", _("Natural (como se lee en clase)")), ("estructural", _("Estructural (marca el inicio y el fin de cada estructura)"))],
			),
			settings.Bool("sayCapitals", _("Decir «&mayúscula» detrás de las letras mayúsculas")),
			settings.Bool("pauses", _("Hacer pa&usas entre las partes de las fórmulas")),
			settings.Choice(
				"browseMode",
				_("Al llegar a una fórmula con la &navegación rápida (tecla 0):"),
				[("speech", _("Leerla como texto (Intro para explorarla)")), ("interactive", _("Empezar a explorarla"))],
			),
			settings.Bool("announceMathRole", _("Anunciar «matemáticas» antes de cada &fórmula en modo exploración")),
			settings.Bool("speakOnEnter", _("Leer la fórmula completa al empezar a e&xplorarla")),
			settings.Bool("brailleMath", _("Mostrar las fórmulas en &braille matemático (Código Matemático Unificado)")),
			settings.Choice(
				"copyFormat",
				_("Formato al copiar con Control+C &durante la exploración:"),
				[("mathml", _("MathML")), ("latex", _("LaTeX")), ("text", _("Texto hablado"))],
			),
		]

	settings.registerPanel("math", _("Matemáticas"), MathPanel)
