"""Empaqueta los complementos de ``data/addons`` como archivos ``.tiresias-addon``.

Uso::

	python tools/package_addons.py [carpeta de salida]
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import addons  # noqa: E402


def main() -> None:
	out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "dist", "complementos")
	os.makedirs(out, exist_ok=True)
	base = os.path.join(ROOT, "data", "addons")
	for entry in sorted(os.listdir(base)):
		folder = os.path.join(base, entry)
		if not os.path.isdir(folder) or entry.startswith(("_", ".")):
			continue
		try:
			# El paquete lleva el identificador del manifiesto (como en tools/publicar.py).
			manifestId = (addons._readManifest(folder) or {}).get("id") or entry
			path = addons.createPackage(folder, os.path.join(out, f"{manifestId}{addons.ADDON_EXTENSION}"))
			print(f"Empaquetado: {path}")
		except ValueError as e:
			print(f"Omitido {entry}: {e}")


if __name__ == "__main__":
	main()
