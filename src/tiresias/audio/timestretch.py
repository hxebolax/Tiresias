"""Cambio de velocidad del audio sin cambiar el tono (WSOLA).

Lo usa el aumento de velocidad de SAPI 5 (las voces SAPI no pasan de su
velocidad máxima) y sirve para cualquier sintetizador que lo necesite.

Algoritmo WSOLA (*waveform similarity overlap-add*): se toman ventanas del
audio original cada ``salto × factor`` muestras y se solapan cada ``salto``
muestras en la salida; cada ventana se desplaza un poco (hasta ``tolerancia``)
para que encaje con la continuación natural de la anterior, lo que evita los
chasquidos y el efecto «robot» del solapamiento simple.
"""

from __future__ import annotations

try:
	import numpy as np
except Exception:  # pragma: no cover
	np = None


def available() -> bool:
	return np is not None


def stretch(pcm: bytes, sampleRate: int, factor: float) -> bytes:
	"""Acelera (``factor`` > 1) o ralentiza PCM mono de 16 bits conservando el tono."""
	try:
		factor = float(factor)
	except (TypeError, ValueError):
		return pcm
	# Fuera de este margen (0, negativo, NaN, infinito o extremos) se devuelve
	# el audio sin cambiar: con 0 se dividía por cero y con factores enormes se
	# reservaban gigas de memoria.
	if not (0.25 <= factor <= 8.0):
		return pcm
	if np is None or abs(factor - 1.0) < 0.02 or len(pcm) < 4:
		return pcm
	x = np.frombuffer(pcm[: len(pcm) - (len(pcm) % 2)], dtype=np.int16).astype(np.float32)
	win = max(64, int(sampleRate * 0.030))
	hop = win // 2
	tol = max(8, int(sampleRate * 0.010))
	if len(x) < win * 2:
		return pcm
	window = np.hanning(win).astype(np.float32)
	nOut = int(len(x) / factor)
	nFrames = nOut // hop + 1
	out = np.zeros(nFrames * hop + win, dtype=np.float32)
	wsum = np.zeros_like(out)
	pad = tol + win
	extra = win + 2 * tol + int(hop * factor) + hop + win
	xp = np.concatenate([np.zeros(pad, dtype=np.float32), x, np.zeros(extra, dtype=np.float32)])
	prev = 0
	for k in range(nFrames):
		nominal = int(k * hop * factor)
		if k == 0:
			pos = nominal
		else:
			target = xp[pad + prev + hop : pad + prev + hop + win]
			start = nominal - tol
			region = xp[pad + start : pad + start + win + 2 * tol]
			if len(region) < win + 2 * tol or not target.any():
				pos = nominal
			else:
				corr = np.correlate(region, target, mode="valid")
				pos = start + int(np.argmax(corr))
		seg = xp[pad + pos : pad + pos + win]
		if len(seg) < win:
			break
		o = k * hop
		out[o : o + win] += seg * window
		wsum[o : o + win] += window
		prev = pos
	out = out[:nOut]
	wsum = wsum[:nOut]
	# En los bordes la suma de ventanas es casi 0: no se amplifica más de 10 veces.
	out = out / np.maximum(wsum, 0.1)
	return np.clip(out, -32768, 32767).astype(np.int16).tobytes()
