"""Genera ``docs/catalogo_complementos.json``: la copia local del catálogo de la tienda.

Uso::

	python tools/make_catalog.py [carpeta de paquetes] [--destino CARPETA_WEB] [--incluir-propietario | --sin-propietario]

Lee los paquetes ``.tiresias-addon`` (por defecto ``dist/complementos``, que
crea ``tools/package_addons.py``) y escribe el catálogo tal y como quedaría
en el servidor de distribución tras publicarlos (con las versiones ya
publicadas en ``--destino``, si existe). Las direcciones son relativas al
catálogo en línea (``complementos/catalogo.json``): la tienda las resuelve
respecto a él aunque lea esta copia local.

Los complementos propietarios (Eloquence) se incluyen o no según
``"incluirPropietario"`` de ``tools/publicar.json`` (la misma decisión que la
publicación); ``--incluir-propietario`` y ``--sin-propietario`` la cambian. El
manifiesto de actualización y la web completa los genera
``tools/publicar.py`` (ver ``docs/publicacion.md``).
"""

from __future__ import annotations

import datetime
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import publicar  # noqa: E402


def main(argv: list[str]) -> int:
	# Misma decisión que la publicación (tools/publicar.json), salvo que se
	# indique lo contrario en la línea de órdenes.
	config = publicar.loadConfig(publicar.CONFIG_FILE)
	include = config.get("incluirPropietario") is True
	if "--incluir-propietario" in argv:
		include = True
	if "--sin-propietario" in argv:
		include = False
	dest = config.get("destino") or publicar.DEFAULT_DEST
	if "--destino" in argv:
		dest = argv[argv.index("--destino") + 1]
	positional = [a for i, a in enumerate(argv) if not a.startswith("--") and (i == 0 or argv[i - 1] != "--destino")]
	packagesDir = positional[0] if positional else os.path.join(ROOT, "dist", "complementos")
	if not os.path.isdir(packagesDir):
		print(f"No existe {packagesDir}: ejecute antes tools/package_addons.py")
		return 1
	packages = [os.path.join(packagesDir, fn) for fn in sorted(os.listdir(packagesDir)) if fn.endswith(".tiresias-addon")]
	previous = publicar.readJson(os.path.join(dest, "complementos", "catalogo.json"), {})
	rel = publicar.Release(publicar.tiresias.VERSION, {}, packages, includeProprietary=include)
	catalog = publicar._simulatedCatalog(os.path.join(dest, "complementos"), rel, previous, datetime.date.today().isoformat())
	path = os.path.join(ROOT, "docs", "catalogo_complementos.json")
	with open(path, "w", encoding="utf-8", newline="\n") as f:
		f.write(publicar.dumpJson(catalog))
	print(f"Catálogo con {len(catalog['addons'])} complementos en docs/catalogo_complementos.json")
	return 0


if __name__ == "__main__":
	sys.exit(main(sys.argv[1:]))
