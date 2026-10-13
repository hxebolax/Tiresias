"""Capa de inteligencia artificial de Tiresias (varios proveedores).

- :mod:`.providers`: Anthropic (Claude), OpenAI, Google Gemini y servidores
  locales compatibles con OpenAI (Ollama, LM Studio).
- :mod:`.keys`: claves del usuario cifradas con DPAPI.
- :mod:`.assistant`: describir, chat de seguimiento, resumir y preguntar sobre
  la página, etiquetas sugeridas, ayuda de Tiresias y CAPTCHA.
- :mod:`.explorer`: explorar la página (contenido, diseño visual y teclas).
- :mod:`.autolabel` y :mod:`.labelstore`: etiquetado automático de los
  elementos sin nombre y textos generados para el modo exploración.
- :mod:`.reading`: orden de lectura y texto alternativo de los PDF con IA.
- :mod:`.captcha`: detectar CAPTCHA, ir al reto de audio y bajar la voz.
- :mod:`.translate`: traducción de la selección, el portapapeles, la última
  locución y, opcionalmente, de todo lo que se dice.
- :mod:`.agent`: agente que realiza tareas en pantalla con confirmación.
- :mod:`.camera`: «Cara a la vista» (encuadre de la cámara, sin red).
"""

from __future__ import annotations

from ..log import getLogger

log = getLogger("ai")


def initialize() -> None:
	from . import assistant  # noqa: F401  (registra los valores por defecto)
	from . import translate

	translate.initialize()
	try:
		from .autolabel import autoLabeler
		from . import captcha

		autoLabeler.initialize()
		captcha.initialize()
	except Exception:
		log.exception("No se pudo iniciar el etiquetado automático o la detección de CAPTCHA")
	try:
		from ..gui import ai_dialogs, settings

		settings.registerPanel("ai", ai_dialogs.AiPanel.title, ai_dialogs.AiPanel)
	except Exception:
		log.exception("No se pudo registrar el panel de inteligencia artificial")


def terminate() -> None:
	from . import translate

	translate.terminate()
	try:
		from .autolabel import autoLabeler
		from . import captcha, reading

		autoLabeler.terminate()
		captcha.terminate()
		if reading._job is not None:
			reading._job.cancel()
	except Exception:
		log.exception("Error cerrando el etiquetado automático o la detección de CAPTCHA")
	try:
		from .agent import agent

		if agent.running:
			agent._stop.set()
			agent._gen += 1
			agent.running = False
	except Exception:
		pass
