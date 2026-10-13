"""Punto de entrada de Tiresias (lector de pantalla)."""

import os
import sys

if not getattr(sys, "frozen", False):
	sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if "--guardian" in sys.argv:
	# Guardián: vuelve a iniciar el lector de pantalla recordado si Tiresias
	# se cierra o falla. Sin wx ni núcleo, para que arranque enseguida.
	from tiresias.coexist import guardian  # noqa: E402

	sys.exit(guardian.main())

if "--console-helper" in sys.argv:
	# Proceso auxiliar sin consola que lee consolas para el lector (console_reader).
	from tiresias import console_reader  # noqa: E402

	sys.exit(console_reader.helperMain())

from tiresias import core  # noqa: E402

if __name__ == "__main__":
	sys.exit(core.main())
