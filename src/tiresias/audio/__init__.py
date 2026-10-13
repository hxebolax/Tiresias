"""Audio de Tiresias: reproductor (WASAPI/waveOut), tonos y sonidos, temas de
sonido de los controles, división del sonido, atenuación y mezclador.

Aquí se registran los valores por defecto de las opciones de audio que no
están en ``config/schema.py`` (se importan siempre antes de usarse).
"""

from __future__ import annotations

from ..config import conf

#: Modos de división del sonido (mismos identificadores que ``sound_split.MODES``).
ALL_SOUND_SPLIT_MODES = ["off", "leftRight", "rightLeft", "leftBoth", "rightBoth", "bothLeft", "bothRight"]

conf.registerDefaults(
	"audio",
	{
		# Salida: "wasapi" (modo compartido, baja latencia) o "waveOut".
		"outputMode": "wasapi",
		# Tamaño del búfer: "low", "normal" o "high" (evita crujidos con CPU alta, #7769).
		"bufferSize": "normal",
		# Ruido blanco para mantener despierto el dispositivo (0 = desactivado, #18435).
		"whiteNoiseVolume": 0,
		# Modos que recorre la orden de división del sonido.
		"includedSoundSplitModes": list(ALL_SOUND_SPLIT_MODES),
		# Los sonidos y pitidos también atenúan las demás aplicaciones.
		"duckForSounds": True,
		# Al arrancar: quitar el silencio del sistema y subir el volumen si está a 0 (#3049).
		"unmuteOnStartup": True,
		"startupVolumeLevel": 40,
		# Mezclador.
		"mixerVolumeStep": 5,
		"micMuteSounds": True,
		# Pedir una segunda pulsación de la tecla Silenciar del teclado (#6427).
		"confirmSystemMute": True,
		# Aviso al cambiar el volumen general: "off", "sound", "speech" o "both" (#6427).
		"volumeChangeFeedback": "off",
	},
)

conf.registerDefaults(
	"earcons",
	{
		# "off", "withSpeech" (sonido y voz) o "insteadOfSpeech" (el sonido sustituye al texto).
		"mode": "off",
		"roles": True,
		"states": True,
		# Panoramizar los sonidos según la posición del objeto en la pantalla.
		"positional": False,
	},
)
