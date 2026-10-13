"""Spotify para Windows.

- Anuncia la canción nueva al cambiar (también en segundo plano).
- La interfaz es una aplicación web: empieza en modo foco para que las
  flechas, el espacio y los atajos lleguen a Spotify (Tiresias+Espacio pasa
  a modo exploración).
"""

from __future__ import annotations

from ._media import MediaAppModule


class AppModule(MediaAppModule):
	disableBrowseModeByDefault = True
	# Spotify tiene varias ventanas: se usa la primera visible con título.
	mainWindowClass = None

	def trackFromTitle(self, title: str) -> str | None:
		# En pausa el título es «Spotify», «Spotify Free» o «Spotify Premium».
		if not title or title.lower().startswith("spotify"):
			return None
		return title
