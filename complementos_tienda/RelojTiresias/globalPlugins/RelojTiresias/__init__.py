"""Reloj para Tiresias.

Tecla de acceso: Tiresias+Control+H. Entra en la capa del reloj
(suena un pitido) y después pulsa una sola letra:

    H  dice la hora
    F  dice la fecha completa
    T  dice la hora y la fecha
    A  activa o desactiva el anuncio periódico de la hora
    I  cambia cada cuánto se anuncia la hora: 60, 30 o 15 minutos
    S  abre el cuadro para elegir el motor de voz y la voz solo
       para el reloj. En el cuadro se elige primero el motor
       (por ejemplo eSpeak NG, las voces de Windows o Piper) y
       después una voz de ese motor. También se puede volver al
       motor y a la voz normal de Tiresias. Solo el reloj habla
       con ese motor y esa voz; Tiresias sigue leyendo todo lo
       demás con su motor y su voz de siempre. Al cambiar de
       motor en el cuadro, la lista de voces cambia a las voces
       de ese motor y la voz vuelve a la normal.
    O  abre la carpeta de sonidos del reloj (clock12 o clock24,
       según el formato), para poner tus propias grabaciones
    G  activa o desactiva el anuncio con grabaciones. Cuando está
       activado y hay un archivo wav para la hora que toca, se
       reproduce la grabación; si no, se dice la hora con la voz.
    C  cambia el formato de la hora entre 12 y 24 horas
    E  dice el estado: si el anuncio está activado, cada cuánto
       se anuncia, qué motor usa solo el reloj, qué voz usa el
       reloj y el formato
    Escape  sale de la capa sin hacer nada

Después de cada función la capa se cierra sola, así que para la
siguiente función se vuelve a pulsar Tiresias+Control+H.

Grabaciones: el complemento trae 48 grabaciones, una por cada cuarto
de hora de 1 a 12 (``sonidos/clock12``), que valen para los dos
formatos. Las grabaciones propias van en la carpeta de datos del
complemento (``addonsData/RelojTiresias/sonidos/clock12`` y
``clock24``), que no se borra al actualizar el complemento; la tecla O
la abre. Si en la carpeta que toca hay un archivo `.wav` con el nombre
de la hora, por ejemplo `03-15.wav` o `15-00.wav`, el reloj reproduce
esa grabación en vez de decir la hora con la voz. Si no hay archivo,
dice la hora con la voz, como siempre. Los archivos son en formato
wav, sin espacios en el nombre.

El anuncio periódico y el formato se guardan en la configuración de
Tiresias (sección RelojTiresias) y se conservan al reiniciar.
El anuncio se hace en horas en punto cuando el intervalo es de
60 minutos, y a las medias y a los cuartos (:00, :15, :30, :45)
cuando es de 30 o 15 minutos."""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from tiresias import queue_handler
from tiresias.baseobject import normalizeGestureId, script
from tiresias.log import getLogger
from tiresias.plugins import GlobalPlugin as _BaseGlobalPlugin

log = getLogger("RelojTiresias")

try:
    import wx
except Exception:
    # Sin wx no hay cuadro de diálogo: en Linux (pruebas) no está.
    wx = None

CATEGORY = "Reloj"
SECTION = "RelojTiresias"

#: Tecla de acceso al complemento: Control + tecla Tiresias + H (de
#: «hora»). Guorco pidió Tiresias+Control+R, pero esa tecla es de Tiresias
#: («Vuelve a la configuración guardada»; tres veces, valores de fábrica)
#: y un complemento va antes que las órdenes de Tiresias: con R el usuario
#: perdía esa orden. Se puede cambiar en Preferencias, Gestos de entrada.
LAYER_ENTRY_GESTURE = "kb:tiresias+control+h"

#: Teclas de la capa -> nombre de la orden (sin el prefijo "script_").
LAYER_GESTURES = {
    "kb:h": "announceTime",
    "kb:f": "announceDate",
    "kb:t": "announceTimeAndDate",
    "kb:a": "toggleHourlyAnnouncement",
    "kb:i": "cycleInterval",
    "kb:s": "openVoiceDialog",
    "kb:o": "openSoundsFolder",
    "kb:g": "toggleRecordings",
    "kb:c": "toggleTimeFormat",
    "kb:e": "announceStatus",
    "kb:escape": "layerExit",
}

INTERVALOS_MINUTOS = (60, 30, 15)

DEFAULTS = {
    # Anunciar la hora periódicamente, aunque no se pulse nada.
    "anunciarCadaHora": False,
    # Cada cuántos minutos se anuncia la hora: 60, 30 o 15.
    "intervaloMinutos": 60,
    # Voz con la que el reloj dice la hora: "" es la voz normal del
    # motor del reloj; si no, el identificador de una voz de ese
    # motor (por ejemplo, una voz de Windows o de eSpeak NG).
    "vozReloj": "",
    # Motor de voz solo para el reloj: "" es el motor de Tiresias;
    # si no, el nombre de otro motor del equipo (por ejemplo
    # "onecore" o "piper"). Solo el reloj habla con ese motor;
    # Tiresias sigue leyendo todo lo demás con su motor de siempre.
    # Se cambia con la tecla S en la capa del reloj.
    "motorReloj": "",
    # Anunciar la hora con grabaciones wav si hay un archivo para
    # esa hora en la carpeta clock12 o clock24. Si no hay archivo,
    # se dice la hora con la voz. Se activa o desactiva con la
    # tecla G en la capa del reloj.
    "usarGrabaciones": True,
    # Formato de la hora: "12" (3:45 de la tarde) o "24" (15:45).
    "formatoHora": "12",
}

DIAS_SEMANA = [
    "lunes", "martes", "miércoles", "jueves",
    "viernes", "sábado", "domingo",
]
MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def _periodo(hora24: int) -> str:
    """'de la mañana', 'de la tarde' o 'de la noche', según la hora."""
    if 5 <= hora24 < 12:
        return "de la mañana"
    if 12 <= hora24 < 21:
        return "de la tarde"
    return "de la noche"


def _hora_en_12(hora24: int) -> int:
    hora12 = hora24 % 12
    return 12 if hora12 == 0 else hora12


def formatTime(momento: datetime, formato: str) -> str:
    """La hora como frase para decirla, por ejemplo 'las 3:45 de la tarde'."""
    if formato == "24":
        verbo = "Es la" if momento.hour == 1 and momento.minute == 0 else "Son las"
        return f"{verbo} {momento.hour}:{momento.minute:02d}"
    hora12 = _hora_en_12(momento.hour)
    verbo = "Es la" if hora12 == 1 else "Son las"
    if momento.minute == 0:
        return f"{verbo} {hora12} {_periodo(momento.hour)}"
    return f"{verbo} {hora12}:{momento.minute:02d} {_periodo(momento.hour)}"


def formatHourOnTheHour(momento: datetime, formato: str) -> str:
    """La hora en punto, para el anuncio de cada hora."""
    if formato == "24":
        verbo = "Es la" if momento.hour == 1 else "Son las"
        return f"{verbo} {momento.hour} en punto"
    hora12 = _hora_en_12(momento.hour)
    verbo = "Es la" if hora12 == 1 else "Son las"
    return f"{verbo} {hora12} {_periodo(momento.hour)} en punto"


def formatDate(momento: datetime) -> str:
    """La fecha completa, por ejemplo 'lunes, 9 de noviembre de 2026'."""
    dia = DIAS_SEMANA[momento.weekday()]
    mes = MESES[momento.month - 1]
    return f"{dia}, {momento.day} de {mes} de {momento.year}"


# ================================================================ grabaciones
#: Carpetas de sonidos dentro de la carpeta del complemento.
SOUNDS_DIR_NAME = "sonidos"
CLOCK12_DIR_NAME = "clock12"
CLOCK24_DIR_NAME = "clock24"
#: Texto que se deja dentro de cada carpeta de sonidos para explicar
#: cómo se llaman los archivos.
SOUNDS_HELP_FILE = "COMO-USAR.txt"
SOUNDS_HELP_TEXT = """Carpeta de grabaciones del reloj de Tiresias.

El complemento ya trae grabaciones de 1 a 12 que valen para los dos
formatos. Esta carpeta es para las tuyas: no se borra al actualizar el
complemento.

Pon aquí tus grabaciones en formato wav, una por cada cuarto de hora.
El nombre es la hora, sin espacios: HH-MM.wav

En clock12, la hora es de 1 a 12:
  01-00.wav, 01-15.wav, 01-30.wav, 01-45.wav,
  02-00.wav, ... hasta 12-45.wav. Son 48 archivos.

En clock24, la hora es de 00 a 23:
  00-00.wav, 00-15.wav, 00-30.wav, 00-45.wav,
  01-00.wav, ... hasta 23-45.wav. Son 96 archivos.
Con el formato de 24 horas, si no hay grabación en clock24 se usa la
de clock12 (las 15:00 usan 03-00.wav).

Si hay un archivo para la hora que toca, el reloj reproduce esa
grabación en vez de decir la hora con la voz. Si no hay archivo,
dice la hora con la voz, como siempre.
"""


ADDON_ID = "RelojTiresias"


def _addonRoot() -> str:
    """Carpeta del complemento (la que tiene manifest.json)."""
    return os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )


def _userRoot() -> str:
    """Carpeta de datos del complemento, para las grabaciones propias.

    Está en ``data\\addonsData\\RelojTiresias``: la carpeta del
    complemento se sustituye entera al actualizarlo desde la tienda,
    y las grabaciones que el usuario pusiera allí se perderían.
    """
    try:
        from tiresias import paths

        return paths.addonDataDir(ADDON_ID)
    except Exception:
        return _addonRoot()


def _soundsFolder(formato: str, addon_root: str | None = None) -> str:
    """Carpeta de grabaciones propias según el formato: clock12 o clock24."""
    root = addon_root or _userRoot()
    carpeta = CLOCK12_DIR_NAME if formato == "12" else CLOCK24_DIR_NAME
    return os.path.join(root, SOUNDS_DIR_NAME, carpeta)


def _recordingFileName(momento: datetime, formato: str) -> str:
    """Nombre del archivo de grabación de una hora: HH-MM.wav."""
    if formato == "12":
        hora = _hora_en_12(momento.hour)
    else:
        hora = momento.hour
    return f"{hora:02d}-{momento.minute:02d}.wav"


def _recordingCandidates(momento: datetime, formato: str, user_root: str | None = None, addon_root: str | None = None) -> list:
    """Archivos que pueden servir para una hora, por orden de preferencia.

    Primero las grabaciones propias del usuario y después las que trae
    el complemento. Las grabaciones de 1 a 12 no dicen «de la mañana» ni
    «de la tarde», así que también valen para el formato de 24 horas
    (``15-00.wav`` usa ``03-00.wav`` si no hay una propia para las 15).
    """
    user = user_root or _userRoot()
    bundled = addon_root or _addonRoot()
    roots = [user] if os.path.normcase(user) == os.path.normcase(bundled) else [user, bundled]
    candidatos = [os.path.join(_soundsFolder(formato, r), _recordingFileName(momento, formato)) for r in roots]
    if formato != "12":
        candidatos += [os.path.join(_soundsFolder("12", r), _recordingFileName(momento, "12")) for r in roots]
    return candidatos


def _recordingPath(momento: datetime, formato: str, user_root: str | None = None, addon_root: str | None = None) -> str | None:
    """Ruta de la grabación de una hora, o None si no hay ninguna."""
    for ruta in _recordingCandidates(momento, formato, user_root, addon_root):
        if os.path.isfile(ruta):
            return ruta
    return None


def _ensureSoundsFolders(addon_root: str | None = None) -> None:
    """Crea las carpetas clock12 y clock24 de las grabaciones propias si no existen."""
    root = addon_root or _userRoot()
    for formato in ("12", "24"):
        carpeta = _soundsFolder(formato, root)
        try:
            os.makedirs(carpeta, exist_ok=True)
            ayuda = os.path.join(carpeta, SOUNDS_HELP_FILE)
            if not os.path.isfile(ayuda):
                with open(ayuda, "w", encoding="utf-8") as f:
                    f.write(SOUNDS_HELP_TEXT)
        except Exception:
            log.debug("No se pudo crear la carpeta de sonidos", exc_info=True)


def getAvailableVoices() -> list:
    """Voces del sintetizador actual: [(id, nombre, idioma)].

    Son las voces disponibles en este equipo para el sintetizador que
    Tiresias está usando ahora (eSpeak NG, voces de Windows, etc.).
    """
    try:
        from tiresias import synth as synthHandler

        synth = synthHandler.getSynth()
        if synth is None:
            return []
        voces = []
        for voice_id, info in synth.availableVoices.items():
            voces.append(
                (
                    str(voice_id),
                    getattr(info, "displayName", str(voice_id)),
                    getattr(info, "language", "") or "",
                )
            )
        return voces
    except Exception:
        log.debug("No se pudieron listar las voces", exc_info=True)
        return []


def getAvailableSynths() -> list:
    """Motores de voz disponibles en este equipo: [(nombre, descripción)].

    Son los sintetizadores que Tiresias puede usar en este equipo
    (eSpeak NG, voces de Windows, Piper, etc.). Se excluye el motor
    "silence", que no suena.
    """
    try:
        from tiresias import synth as synthHandler

        return [
            (str(nombre), str(descripcion) or str(nombre))
            for nombre, descripcion in synthHandler.getSynthList()
            if nombre != "silence"
        ]
    except Exception:
        log.debug("No se pudieron listar los motores de voz", exc_info=True)
        return []


def getCurrentSynth() -> tuple:
    """Motor de voz que Tiresias está usando ahora: (nombre, descripción)."""
    try:
        from tiresias import synth as synthHandler

        synth = synthHandler.getSynth()
        if synth is None:
            return ("", "")
        nombre = str(getattr(synth, "name", "") or "")
        descripcion = str(getattr(synth, "description", "") or nombre)
        return (nombre, descripcion)
    except Exception:
        log.debug("No se pudo saber el motor de voz actual", exc_info=True)
        return ("", "")


def _instantiateSynth(name: str):
    """Crea un sintetizador aparte, sin tocar el de Tiresias.

    Devuelve el controlador o None si no se pudo crear. Usa las
    funciones internas de Tiresias para crear el controlador (las
    mismas que usa al cambiar de sintetizador); si no están, crea
    el controlador directamente. No todos los motores permiten
    tener una segunda copia abierta a la vez: si falla, el reloj
    vuelve a la voz de Tiresias.
    """
    try:
        from tiresias import synth as synthHandler

        instantiate = getattr(synthHandler, "_instantiate", None)
        if instantiate is not None:
            return instantiate(name)
        cls = synthHandler._getDriverClass(name)
        driver = cls()
        try:
            driver.loadSettings(synthHandler._settingsSection(name))
        except Exception:
            pass
        return driver
    except Exception:
        log.debug("No se pudo crear el sintetizador %s", name, exc_info=True)
        return None


def _speak(text: str, voice_id: str | None = None) -> None:
    """Dice un texto con la voz de Tiresias, también en modo a demanda.

    Si ``voice_id`` es una voz válida del sintetizador actual, el texto
    se dice con esa voz y solo para este mensaje: Tiresias usa
    ``VoiceCommand`` y vuelve a su voz normal después. Si no hay voz
    elegida o ya no existe, se usa la voz normal de Tiresias.
    """
    try:
        from tiresias import speech

        with speech.allowOnDemand():
            if voice_id:
                from tiresias.speech.commands import VoiceCommand

                speech.speak([VoiceCommand(voice_id), text])
                try:
                    from tiresias import braille

                    braille.handler.message(text)
                except Exception:
                    pass
            else:
                speech.speakMessage(text)
    except Exception:
        log.debug("No se pudo decir el texto del reloj", exc_info=True)


def _isStandby() -> bool:
    """True si Tiresias está en espera porque otro lector tiene preferencia."""
    try:
        from tiresias import coexist

        return bool(coexist.isStandby())
    except Exception:
        return False


def _beep(hz: int, ms: int) -> None:
    try:
        from tiresias.audio import tones

        tones.beep(hz, ms)
    except Exception:
        pass


def _dialogParent():
    """Ventana principal de Tiresias, para que el cuadro sea hijo suyo.

    Es lo mismo que hace Tiresias para sus propios cuadros
    (por ejemplo, el de elegir sintetizador).
    """
    try:
        app = wx.GetApp()
        if app is None:
            return None
        return app.GetTopWindow()
    except Exception:
        return None


if wx is not None:

    class ClockVoiceDialog(wx.Dialog):
        """Cuadro para elegir el motor de voz y la voz solo para el reloj.

        Dos listas: "Motor de voz" y "Voz". Al cambiar de motor, la
        lista de voces se cambia por las voces de ese motor y la voz
        vuelve a la normal. Aceptar aplica lo elegido; Cancelar (o
        Escape) no cambia nada. Tiene el mismo estilo que el cuadro
        de Tiresias para elegir sintetizador: botones Aceptar y
        Cancelar, y la primera lista con el foco al abrir.

        El cuadro NO es modal: se abre en el hilo de la interfaz y
        no bloquea el hilo del núcleo. Por eso la lista de voces
        se lee en el núcleo y se pasa al cuadro con ``wx.CallAfter``
        (igual que hace el panel de voz de Tiresias), y al aceptar
        se encola la aplicación en el núcleo. Un cuadro modal con
        ``ShowModal`` desde una tecla trababa Tiresias: el núcleo
        quedaba bloqueado, el vigilante lo reiniciaba y volvía el
        otro lector de pantalla.
        """

        def __init__(self, plugin, synth_options, current_synth, voices, current_voice):
            super().__init__(
                _dialogParent(),
                title="Voz del reloj",
                style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            )
            self._plugin = plugin
            self._closed = False
            self._synthValues = [valor for valor, _et in synth_options]
            etiquetas_motor = [et for _v, et in synth_options]
            sel_motor = (
                self._synthValues.index(current_synth)
                if current_synth in self._synthValues
                else 0
            )
            main = wx.BoxSizer(wx.VERTICAL)
            main.Add(wx.StaticText(self, label="Motor de voz:"), 0, wx.ALL, 4)
            self.synthChoice = wx.Choice(self, choices=etiquetas_motor)
            self.synthChoice.SetSelection(sel_motor)
            main.Add(self.synthChoice, 0, wx.EXPAND | wx.ALL, 4)
            main.Add(wx.StaticText(self, label="Voz:"), 0, wx.ALL, 4)
            self.voiceChoice = wx.Choice(self, choices=[])
            main.Add(self.voiceChoice, 0, wx.EXPAND | wx.ALL, 4)
            self._setVoices(voices, current_voice)
            buttons = wx.StdDialogButtonSizer()
            ok = wx.Button(self, wx.ID_OK, "Aceptar")
            cancel = wx.Button(self, wx.ID_CANCEL, "Cancelar")
            buttons.AddButton(ok)
            buttons.AddButton(cancel)
            buttons.Realize()
            main.Add(buttons, 0, wx.ALIGN_RIGHT | wx.TOP, 8)
            self.SetSizer(main)
            main.Fit(self)
            ok.SetDefault()
            self.SetEscapeId(wx.ID_CANCEL)
            ok.Bind(wx.EVT_BUTTON, self._onOk)
            cancel.Bind(wx.EVT_BUTTON, self._onCancel)
            self.synthChoice.Bind(wx.EVT_CHOICE, self._onSynthChoice)
            self.Bind(wx.EVT_CLOSE, self._onClose)
            self.CentreOnScreen()
            self.synthChoice.SetFocus()

        def _setVoices(self, voices, select_voice: str = "") -> None:
            """Pone una lista de voces en el cuadro."""
            self._voiceValues = [""] + [
                voice_id for voice_id, _n, _i in voices
            ]
            etiquetas = ["La voz normal"] + [
                nombre for _id, nombre, _i in voices
            ]
            self.voiceChoice.Set(etiquetas)
            seleccion = (
                self._voiceValues.index(select_voice)
                if select_voice in self._voiceValues
                else 0
            )
            self.voiceChoice.SetSelection(seleccion)

        def _updateVoices(self, voices) -> None:
            """Pone las voces leídas en el hilo del núcleo.

            Se llama con ``wx.CallAfter`` desde el núcleo, así que
            el cuadro puede haberse cerrado ya: en ese caso no se
            hace nada.
            """
            if self._closed:
                return
            try:
                # Al cambiar de motor, la voz vuelve a la normal.
                self._setVoices(voices)
            except Exception:
                pass

        def _onSynthChoice(self, evt) -> None:
            # Las voces del motor nuevo se leen en el hilo del
            # núcleo (ahí viven los sintetizadores) y se pasan al
            # cuadro con wx.CallAfter, como hace el panel de voz
            # de Tiresias. Mientras tanto, la lista queda en
            # "Cargando..." y la voz en la normal.
            synth = self.selectedSynth()
            self.voiceChoice.Set(["Cargando..."])
            self.voiceChoice.SetSelection(0)
            queue_handler.queueFunction(
                _collectDialogVoices, self._plugin, self, synth
            )

        def _onOk(self, evt) -> None:
            # La aplicación va al hilo del núcleo (ahí viven los
            # sintetizadores) y el cuadro se cierra ya.
            synth = self.selectedSynth()
            voice = self.selectedVoice()
            queue_handler.queueFunction(
                self._plugin._applyFromDialog, synth, voice
            )
            self.Close()

        def _onCancel(self, evt) -> None:
            self.Close()

        def _onClose(self, evt) -> None:
            self._closed = True
            if (
                self._plugin is not None
                and getattr(self._plugin, "_voiceDialog", None) is self
            ):
                self._plugin._voiceDialog = None
            self.Destroy()

        def selectedSynth(self) -> str:
            i = self.synthChoice.GetSelection()
            if 0 <= i < len(self._synthValues):
                return self._synthValues[i]
            return ""

        def selectedVoice(self) -> str:
            i = self.voiceChoice.GetSelection()
            if 0 <= i < len(self._voiceValues):
                return self._voiceValues[i]
            return ""

else:
    ClockVoiceDialog = None


def _showClockVoiceDialog(plugin, synth_options, current_synth, voices, current_voice):
    """Crea y muestra el cuadro de voz del reloj (hilo de la interfaz)."""
    try:
        dlg = ClockVoiceDialog(
            plugin, synth_options, current_synth, voices, current_voice
        )
    except Exception:
        log.debug("No se pudo abrir el cuadro de voz del reloj", exc_info=True)
        return
    plugin._voiceDialog = dlg
    _bringToFront(dlg)


def _bringToFront(dlg) -> None:
    """Muestra el cuadro y lo trae al primer plano (hilo de la interfaz).

    Igual que hace Tiresias con sus propios cuadros: Show, Raise y
    ponerlo en primer plano con winapi, para que no se quede detrás
    de otras ventanas. Sin esto, el cuadro a veces aparecía en
    segundo plano y Guorco tenía que buscarlo.
    """
    try:
        if dlg.IsIconized():
            dlg.Iconize(False)
    except Exception:
        pass
    try:
        if not dlg.IsShown():
            dlg.Show()
    except Exception:
        pass
    try:
        dlg.Raise()
    except Exception:
        pass
    try:
        from tiresias import winapi

        winapi.setForegroundWindow(dlg.GetHandle())
    except Exception:
        pass


def _collectDialogVoices(plugin, dlg, synth_name: str) -> None:
    """Lee las voces de un motor (hilo del núcleo) y las pasa al cuadro."""
    try:
        voices = plugin._voicesForSynth(synth_name)
    except Exception:
        voices = []
    try:
        wx.CallAfter(dlg._updateVoices, voices)
    except Exception:
        pass


class GlobalPlugin(_BaseGlobalPlugin):
    scriptCategory = CATEGORY

    def __init__(self) -> None:
        super().__init__()
        self._terminated = False
        self._isLayerActive = False
        self._layerIds = frozenset(
            normalizeGestureId(g)
            for g in (*LAYER_GESTURES, LAYER_ENTRY_GESTURE)
        )
        self._hourTimerId = None
        # Sintetizador aparte solo para el reloj (None si el reloj
        # usa el motor de Tiresias). Se crea al elegir otro motor
        # con la tecla S y se cierra al salir de Tiresias.
        self._clockSynth = None
        self._clockSynthLoadedName = ""
        # Voces leídas de cada motor mientras el cuadro de voz está
        # abierto, para no abrir el motor a cada cambio de lista.
        self._voiceCache = {}
        # Cuadro de voz abierto, si lo hay (solo uno a la vez).
        self._voiceDialog = None
        try:
            from tiresias.config import conf

            conf.registerDefaults(SECTION, DEFAULTS)
        except Exception:
            log.debug("No se pudo registrar la configuración del reloj", exc_info=True)
        # Al cargar el complemento se crean las carpetas de sonidos
        # clock12 y clock24, para que el usuario pueda poner sus
        # grabaciones (versión 1.3.0).
        _ensureSoundsFolders()
        try:
            from tiresias.input import core as inputCore

            inputCore.decide_executeGesture.register(self._decideExecuteGesture)
        except Exception:
            log.debug("No se pudo registrar la capa del reloj", exc_info=True)
        if self._get("anunciarCadaHora"):
            self._scheduleNextAnnouncement()

    def terminate(self) -> None:
        self._terminated = True
        self._cancelAnnouncementTimer()
        self._terminateClockSynth()
        try:
            from tiresias.input import core as inputCore

            inputCore.decide_executeGesture.unregister(self._decideExecuteGesture)
        except Exception:
            pass
        self._finishLayer()
        super().terminate()

    # ================================================================ configuración
    def _get(self, key: str):
        try:
            from tiresias.config import conf

            return conf[SECTION][key]
        except Exception:
            return DEFAULTS[key]

    def _set(self, key: str, value) -> None:
        try:
            from tiresias.config import conf

            conf[SECTION][key] = value
        except Exception:
            log.debug("No se pudo guardar la configuración del reloj", exc_info=True)

    def _intervalo(self) -> int:
        intervalo = self._get("intervaloMinutos")
        try:
            intervalo = int(intervalo)
        except Exception:
            return DEFAULTS["intervaloMinutos"]
        return intervalo if intervalo in INTERVALOS_MINUTOS else DEFAULTS["intervaloMinutos"]

    def _formato(self) -> str:
        formato = self._get("formatoHora")
        return formato if formato in ("12", "24") else DEFAULTS["formatoHora"]

    def _clockSynthName(self) -> str:
        """Nombre del motor solo para el reloj, o "" si es el de Tiresias.

        Si el motor guardado es el mismo que está usando Tiresias,
        no hace falta un segundo motor: el reloj usa el de Tiresias.
        """
        motor = self._get("motorReloj") or ""
        if not motor:
            return ""
        nombre_actual, _desc = getCurrentSynth()
        return "" if motor == nombre_actual else motor

    def _ensureClockSynth(self, nombre: str | None = None):
        """El sintetizador aparte del reloj, o None si usa el de Tiresias.

        El motor aparte se crea una sola vez y se guarda para
        reutilizarlo en cada anuncio; si no se pudo crear, se
        devuelve None y el reloj habla con el motor de Tiresias.
        """
        if nombre is None:
            nombre = self._clockSynthName()
        if not nombre:
            if self._clockSynth is not None:
                # Tiresias usa ahora el motor del reloj: el reloj habla con
                # el de Tiresias y suelta su copia (sin cerrarla si es el
                # mismo motor; ver _terminateClockSynth).
                self._terminateClockSynth()
            return None
        if self._clockSynth is not None and self._clockSynthLoadedName == nombre:
            return self._clockSynth
        self._terminateClockSynth()
        driver = _instantiateSynth(nombre)
        if driver is None:
            return None
        self._clockSynth = driver
        self._clockSynthLoadedName = nombre
        # Si hay una voz guardada para el reloj y existe en este
        # motor, se aplica. Si no, el motor usa su voz normal.
        voz = self._get("vozReloj") or ""
        if voz:
            try:
                if voz in driver.availableVoices:
                    driver.setSetting("voice", voz)
            except Exception:
                pass
        return driver

    def _terminateClockSynth(self) -> None:
        """Cierra el sintetizador aparte del reloj, si lo hay.

        Si Tiresias ha pasado a usar el mismo motor (por ejemplo, eSpeak
        NG), no se cierra: eSpeak y Eloquence tienen una sola biblioteca
        por proceso y cerrar la copia del reloj dejaría sin voz a Tiresias.
        Solo se suelta.
        """
        driver = getattr(self, "_clockSynth", None)
        nombre_actual, _desc = getCurrentSynth()
        if driver is not None and self._clockSynthLoadedName == nombre_actual:
            driver = None
        if driver is not None:
            try:
                driver.cancel()
            except Exception:
                pass
            try:
                driver.terminate()
            except Exception:
                pass
        self._clockSynth = None
        self._clockSynthLoadedName = ""

    def _synthOptions(self) -> list:
        """Motores para el cuadro de voz: [(valor, etiqueta)].

        El valor "" es el motor de Tiresias; los demás son los
        motores del equipo, sin repetir el de Tiresias y sin el
        motor "silence", que no suena.
        """
        nombre_actual, desc_actual = getCurrentSynth()
        if desc_actual:
            opciones = [("", f"El de Tiresias ({desc_actual})")]
        else:
            opciones = [("", "El de Tiresias")]
        for nombre, descripcion in getAvailableSynths():
            if nombre != nombre_actual:
                opciones.append((nombre, descripcion or nombre))
        return opciones

    def _voicesForSynth(self, synth_name: str) -> list:
        """Voces de un motor, para el cuadro de voz: [(id, nombre, idioma)].

        Si es el motor de Tiresias, son sus voces. Si es otro motor,
        se abre una copia aparte solo para leer sus voces y se
        cierra; si no se puede abrir, la lista sale vacía (en el
        cuadro solo queda "La voz normal"). Las voces leídas se
        guardan mientras el cuadro está abierto, para no abrir el
        motor a cada cambio de lista.
        """
        if not synth_name:
            return getAvailableVoices()
        if (
            self._clockSynth is not None
            and self._clockSynthLoadedName == synth_name
        ):
            try:
                return [
                    (
                        str(voice_id),
                        getattr(info, "displayName", str(voice_id)),
                        getattr(info, "language", "") or "",
                    )
                    for voice_id, info in self._clockSynth.availableVoices.items()
                ]
            except Exception:
                log.debug(
                    "No se pudieron listar las voces del motor del reloj",
                    exc_info=True,
                )
                return []
        cache = self._voiceCache
        if synth_name in cache:
            return cache[synth_name]
        voces = []
        driver = _instantiateSynth(synth_name)
        if driver is not None:
            try:
                voces = [
                    (
                        str(voice_id),
                        getattr(info, "displayName", str(voice_id)),
                        getattr(info, "language", "") or "",
                    )
                    for voice_id, info in driver.availableVoices.items()
                ]
            except Exception:
                log.debug(
                    "No se pudieron listar las voces de %s",
                    synth_name,
                    exc_info=True,
                )
                voces = []
            try:
                driver.cancel()
            except Exception:
                pass
            try:
                driver.terminate()
            except Exception:
                pass
        cache[synth_name] = voces
        return voces

    def applyVoiceChoice(self, synth_name: str, voice_id: str):
        """Aplica lo elegido en el cuadro de voz del reloj.

        ``synth_name`` es "" para el motor de Tiresias o el nombre
        de otro motor; ``voice_id`` es "" para la voz normal o el
        identificador de una voz de ese motor. Devuelve None si se
        aplicó, o el mensaje de error si el motor no se pudo abrir
        aparte: en ese caso se vuelve a lo que había antes.
        """
        old_motor = self._get("motorReloj") or ""
        old_voz = self._get("vozReloj") or ""
        if not synth_name:
            # Motor de Tiresias: se cierra el motor aparte, si lo hay.
            self._terminateClockSynth()
            self._set("motorReloj", "")
            self._set("vozReloj", voice_id or "")
            return None
        self._set("motorReloj", synth_name)
        self._set("vozReloj", voice_id or "")
        # Motor nuevo: se abre de nuevo, para que la voz sea la
        # elegida y no la que tenía el motor anterior.
        self._terminateClockSynth()
        if self._ensureClockSynth(synth_name) is None:
            # No se pudo abrir aparte: se vuelve a lo que había.
            self._set("motorReloj", old_motor)
            self._set("vozReloj", old_voz)
            self._ensureClockSynth()
            desc = dict(getAvailableSynths()).get(synth_name, synth_name)
            return (
                f"No se pudo usar el motor {desc} solo para el reloj. "
                "Se sigue usando el motor del reloj que tenías."
            )
        return None

    def _applyFromDialog(self, synth_name: str, voice_id: str) -> None:
        """Aplica lo elegido en el cuadro y lo anuncia (hilo del núcleo).

        Se llama desde el botón Aceptar del cuadro, que vive en el
        hilo de la interfaz: por eso va encolado en el núcleo, que
        es donde viven los sintetizadores y la voz.
        """
        error = self.applyVoiceChoice(synth_name, voice_id)
        if error:
            self._say(error)
            return
        _nombre, desc_actual = getCurrentSynth()
        motor = self._clockSynthName()
        if motor:
            desc_motor = dict(getAvailableSynths()).get(motor, motor)
            motor_texto = desc_motor
        else:
            motor_texto = f"el de Tiresias ({desc_actual})"
        self._say(
            f"Motor del reloj: {motor_texto}. "
            f"Voz del reloj: {self._getClockVoiceName()}. "
            f"{formatTime(datetime.now(), self._formato())}."
        )

    def _getClockVoices(self) -> list:
        """Voces del motor del reloj: [(id, nombre, idioma)].

        Son las voces del motor aparte si el reloj tiene uno, y si
        no, las voces del motor que está usando Tiresias.
        """
        driver = self._ensureClockSynth()
        if driver is not None:
            try:
                return [
                    (
                        str(voice_id),
                        getattr(info, "displayName", str(voice_id)),
                        getattr(info, "language", "") or "",
                    )
                    for voice_id, info in driver.availableVoices.items()
                ]
            except Exception:
                log.debug(
                    "No se pudieron listar las voces del motor del reloj",
                    exc_info=True,
                )
        return getAvailableVoices()

    def _getClockVoiceId(self) -> str | None:
        """Id de la voz elegida para el reloj, o None si es la normal.

        Si la voz guardada ya no existe en el motor del reloj (por
        ejemplo, porque se cambió de motor), se ignora y se usa la
        voz normal.
        """
        guardada = self._get("vozReloj")
        if not guardada:
            return None
        for voice_id, _nombre, _idioma in self._getClockVoices():
            if voice_id == guardada:
                return guardada
        return None

    def _getClockVoiceName(self) -> str:
        guardada = self._get("vozReloj")
        if not guardada:
            return "la voz normal"
        for voice_id, nombre, _idioma in self._getClockVoices():
            if voice_id == guardada:
                return nombre
        return "la voz normal"

    def _say(self, text: str) -> None:
        """Dice un texto con la voz del reloj.

        Si el reloj tiene su propio motor, el texto se dice con ese
        motor, sin tocar el motor de Tiresias. Si no, se dice con la
        voz elegida para el reloj en el motor de Tiresias, y solo
        para este mensaje: Tiresias vuelve a su voz normal después.
        """
        driver = self._ensureClockSynth()
        if driver is not None:
            try:
                driver.cancel()
                driver.speak([text])
                try:
                    from tiresias import braille

                    braille.handler.message(text)
                except Exception:
                    pass
                return
            except Exception:
                log.debug(
                    "No se pudo decir con el motor del reloj",
                    exc_info=True,
                )
        _speak(text, self._getClockVoiceId())

    def _playRecordingFor(self, momento: datetime) -> bool:
        """Reproduce la grabación de una hora, si existe y está activada.

        Devuelve True si se reprodujo un archivo wav, False si no hay
        archivo para esa hora o si las grabaciones están desactivadas.
        En ese caso, quien llama debe decir la hora con la voz.
        """
        if not self._get("usarGrabaciones"):
            return False
        ruta = _recordingPath(momento, self._formato())
        if ruta is None:
            return False
        try:
            from tiresias.audio import tones

            tones.playWaveFile(ruta)
            return True
        except Exception:
            log.debug("No se pudo reproducir la grabación %s", ruta, exc_info=True)
            return False

    # ================================================================ anuncio periódico
    def _cancelAnnouncementTimer(self) -> None:
        if self._hourTimerId is not None:
            try:
                queue_handler.cancelCallLater(self._hourTimerId)
            except Exception:
                pass
            self._hourTimerId = None

    def _nextAnnouncementTime(self, ahora: datetime) -> datetime:
        """La próxima hora de anuncio, alineada al intervalo.

        Con 60 minutos es la próxima hora en punto; con 30, la próxima
        media o hora en punto; con 15, el próximo cuarto (:00, :15, :30
        o :45). Si ahora mismo es justo un momento de anuncio, se espera
        al siguiente, para no anunciar dos veces seguidas.
        """
        intervalo = self._intervalo()
        base = ahora.replace(second=0, microsecond=0)
        minutos_desde_hora = base.minute
        resto = minutos_desde_hora % intervalo
        if resto == 0:
            # Estamos en un momento de anuncio: si falta más de
            # 2 segundos para el instante exacto, es este mismo;
            # si no, el siguiente, para no anunciar dos veces.
            if (base - ahora).total_seconds() > 2:
                return base
            return base + timedelta(minutes=intervalo)
        return base + timedelta(minutes=intervalo - resto)

    def _scheduleNextAnnouncement(self) -> None:
        """Programa el próximo aviso de la hora."""
        self._cancelAnnouncementTimer()
        if self._terminated:
            return
        ahora = datetime.now()
        proximo = self._nextAnnouncementTime(ahora)
        # Medio segundo después del momento exacto, para que el reloj
        # ya haya cambiado y no se anuncie la hora anterior.
        retraso_ms = int((proximo - ahora).total_seconds() * 1000) + 500
        self._hourTimerId = queue_handler.callLater(retraso_ms, self._onAnnouncement)

    def _onAnnouncement(self) -> None:
        """Llega en el hilo del núcleo cuando toca anunciar la hora."""
        self._hourTimerId = None
        if self._terminated or not self._get("anunciarCadaHora"):
            return
        if _isStandby():
            # Tiresias está en espera porque habla otro lector de pantalla:
            # el reloj no habla por encima de él. Sigue contando.
            self._scheduleNextAnnouncement()
            return
        ahora = datetime.now()
        # Si hay una grabación para esta hora, se reproduce. Si no,
        # se dice la hora con la voz, como siempre.
        if not self._playRecordingFor(ahora):
            if ahora.minute == 0:
                self._say(formatHourOnTheHour(ahora, self._formato()))
            else:
                self._say(formatTime(ahora, self._formato()))
        self._scheduleNextAnnouncement()

    # ================================================================ capa de órdenes
    def _decideExecuteGesture(self, gesture) -> bool:
        """Sale de la capa antes de resolver una tecla que no es de la capa.

        Se llama en el hilo de los ganchos: solo quita las asignaciones
        (rápido) y deja que la tecla siga su camino (llega a la aplicación).
        """
        if self._isLayerActive and not getattr(gesture, "isModifier", False):
            ids = {normalizeGestureId(i) for i in getattr(gesture, "identifiers", ()) or ()}
            if self._layerIds.isdisjoint(ids):
                self._finishLayer()
        return True

    def _finishLayer(self) -> None:
        self._isLayerActive = False
        inst = self.__dict__.get("_instanceGestures")
        if inst is None:
            return
        for gestureId in LAYER_GESTURES:
            inst.pop(gestureId, None)

    @script(
        description="Entra en la capa del reloj. Después pulsa H para la hora, F para la fecha, T para la hora y la fecha, A para activar o desactivar el anuncio de la hora, I para cambiar cada cuánto se anuncia (60, 30 o 15 minutos), S para abrir el cuadro donde se eligen el motor de voz y la voz solo para el reloj, O para abrir la carpeta de sonidos, G para activar o desactivar el anuncio con grabaciones, C para cambiar el formato de 12 a 24 horas, E para oír el estado, o Escape para salir.",
        category=CATEGORY,
        gesture=LAYER_ENTRY_GESTURE,
    )
    def script_layerEntry(self, gesture) -> None:
        if self._isLayerActive:
            return
        self.bindGestures(LAYER_GESTURES)
        self._isLayerActive = True
        _beep(660, 70)
        try:
            from tiresias import braille

            braille.handler.message(CATEGORY)
        except Exception:
            pass

    @script(
        description="Sale de la capa del reloj",
        category=CATEGORY,
        allowInSleepMode=True,
    )
    def script_layerExit(self, gesture) -> None:
        self._finishLayer()
        _beep(440, 80)

    # ================================================================ órdenes del reloj
    @script(
        description="Dice la hora. Si es una hora en punto o un cuarto y hay una grabación para esa hora, reproduce la grabación.",
        category=CATEGORY,
        speakOnDemand=True,
    )
    def script_announceTime(self, gesture) -> None:
        ahora = datetime.now()
        # Solo tiene sentido la grabación en los cuartos de hora
        # (:00, :15, :30, :45), que son los que tienen archivo.
        if ahora.minute % 15 == 0 and self._playRecordingFor(ahora):
            self._finishLayer()
            return
        self._say(formatTime(ahora, self._formato()))
        self._finishLayer()

    @script(
        description="Dice la fecha completa",
        category=CATEGORY,
        speakOnDemand=True,
    )
    def script_announceDate(self, gesture) -> None:
        self._say(formatDate(datetime.now()))
        self._finishLayer()

    @script(
        description="Dice la hora y la fecha",
        category=CATEGORY,
        speakOnDemand=True,
    )
    def script_announceTimeAndDate(self, gesture) -> None:
        ahora = datetime.now()
        self._say(
            f"{formatTime(ahora, self._formato())}. {formatDate(ahora)}."
        )
        self._finishLayer()

    @script(
        description="Activa o desactiva el anuncio periódico de la hora",
        category=CATEGORY,
        speakOnDemand=True,
    )
    def script_toggleHourlyAnnouncement(self, gesture) -> None:
        activado = not bool(self._get("anunciarCadaHora"))
        self._set("anunciarCadaHora", activado)
        if activado:
            self._scheduleNextAnnouncement()
            proximo = self._nextAnnouncementTime(datetime.now())
            if self._formato() == "24":
                proximo_texto = f"a las {proximo.hour}:{proximo.minute:02d}"
            elif proximo.minute == 0:
                proximo_texto = (
                    f"a las {_hora_en_12(proximo.hour)} "
                    f"{_periodo(proximo.hour)}"
                )
            else:
                proximo_texto = (
                    f"a las {_hora_en_12(proximo.hour)}:"
                    f"{proximo.minute:02d} {_periodo(proximo.hour)}"
                )
            self._say(
                "Anuncio de la hora activado, "
                f"cada {self._intervalo()} minutos. "
                f"El próximo aviso será {proximo_texto}."
            )
        else:
            self._cancelAnnouncementTimer()
            self._say("Anuncio de la hora desactivado.")
        self._finishLayer()

    @script(
        description="Cambia cada cuánto se anuncia la hora: 60, 30 o 15 minutos",
        category=CATEGORY,
        speakOnDemand=True,
    )
    def script_cycleInterval(self, gesture) -> None:
        actual = self._intervalo()
        siguiente = INTERVALOS_MINUTOS[
            (INTERVALOS_MINUTOS.index(actual) + 1) % len(INTERVALOS_MINUTOS)
        ]
        self._set("intervaloMinutos", siguiente)
        if self._get("anunciarCadaHora"):
            # Reprogramar con el intervalo nuevo.
            self._scheduleNextAnnouncement()
            self._say(
                f"La hora se anunciará cada {siguiente} minutos."
            )
        else:
            self._say(
                f"Intervalo cambiado a cada {siguiente} minutos. "
                "El anuncio está desactivado; actívalo con la tecla A."
            )
        self._finishLayer()

    @script(
        description="Abre el cuadro para elegir el motor de voz y la voz solo para el reloj. En el cuadro se elige primero el motor (por ejemplo eSpeak NG, las voces de Windows o Piper) y después una voz de ese motor; también se puede volver al motor y a la voz normal de Tiresias. Solo el reloj habla con ese motor y esa voz; Tiresias sigue leyendo todo lo demás con su motor de siempre. Aceptar aplica lo elegido; Cancelar no cambia nada.",
        category=CATEGORY,
        speakOnDemand=True,
    )
    def script_openVoiceDialog(self, gesture) -> None:
        # Se sale de la capa antes de abrir el cuadro, para que sus
        # teclas (flechas, Tab, Enter, Escape) lleguen al cuadro y
        # no a la capa del reloj.
        self._finishLayer()
        if ClockVoiceDialog is None or wx is None:
            self._say(
                "No se pudo abrir el cuadro de voz del reloj en este equipo."
            )
            return
        if getattr(self, "_voiceDialog", None) is not None:
            # Ya hay un cuadro abierto: se trae al frente y no se
            # abre otro. Va al hilo de la interfaz.
            wx.CallAfter(self._bringVoiceDialogToFront)
            return
        # Las opciones se leen aquí, en el hilo del núcleo (aquí
        # corren las teclas y aquí viven los sintetizadores), y el
        # cuadro se crea y se muestra en el hilo de la interfaz
        # con wx.CallAfter. El cuadro NO es modal y la tecla NO
        # espera a que se cierre: un cuadro modal con ShowModal
        # desde una tecla dejaba el núcleo bloqueado, el vigilante
        # de Tiresias lo reiniciaba y volvía el otro lector.
        self._voiceCache = {}
        opciones = self._synthOptions()
        actual_motor = self._clockSynthName()
        voces = self._voicesForSynth(actual_motor)
        actual_voz = self._get("vozReloj") or ""
        try:
            wx.CallAfter(
                _showClockVoiceDialog,
                self,
                opciones,
                actual_motor,
                voces,
                actual_voz,
            )
        except Exception:
            log.debug(
                "No se pudo abrir el cuadro de voz del reloj",
                exc_info=True,
            )
            self._say("No se pudo abrir el cuadro de voz del reloj.")

    def _bringVoiceDialogToFront(self) -> None:
        """Trae al frente el cuadro de voz ya abierto (hilo de la interfaz)."""
        dlg = getattr(self, "_voiceDialog", None)
        if dlg is None:
            return
        _bringToFront(dlg)
        try:
            dlg.synthChoice.SetFocus()
        except Exception:
            pass

    @script(
        description="Abre la carpeta de sonidos del reloj (clock12 o clock24, según el formato), para poner tus propias grabaciones en wav",
        category=CATEGORY,
        speakOnDemand=True,
    )
    def script_openSoundsFolder(self, gesture) -> None:
        _ensureSoundsFolders()
        carpeta = _soundsFolder(self._formato())
        nombre = CLOCK12_DIR_NAME if self._formato() == "12" else CLOCK24_DIR_NAME
        abierto = False
        try:
            startfile = getattr(os, "startfile", None)
            if startfile is not None:
                startfile(carpeta)
                abierto = True
        except Exception:
            log.debug("No se pudo abrir la carpeta de sonidos", exc_info=True)
        if abierto:
            self._say(f"Carpeta {nombre} abierta.")
        else:
            self._say(
                f"No se pudo abrir la carpeta {nombre}. "
                f"Está en {carpeta}."
            )
        self._finishLayer()

    @script(
        description="Activa o desactiva el anuncio de la hora con grabaciones. Cuando está activado y hay un archivo wav para la hora que toca, se reproduce la grabación; si no, se dice la hora con la voz.",
        category=CATEGORY,
        speakOnDemand=True,
    )
    def script_toggleRecordings(self, gesture) -> None:
        activado = not bool(self._get("usarGrabaciones"))
        self._set("usarGrabaciones", activado)
        if activado:
            self._say(
                "Anuncio con grabaciones activado. Si hay un archivo "
                "wav para la hora que toca, se reproducirá la grabación; "
                "si no, se dirá la hora con la voz."
            )
        else:
            self._say(
                "Anuncio con grabaciones desactivado. La hora siempre "
                "se dirá con la voz."
            )
        self._finishLayer()

    @script(
        description="Cambia el formato de la hora entre 12 y 24 horas",
        category=CATEGORY,
        speakOnDemand=True,
    )
    def script_toggleTimeFormat(self, gesture) -> None:
        nuevo = "24" if self._formato() == "12" else "12"
        self._set("formatoHora", nuevo)
        self._say(
            f"Formato de la hora cambiado a {nuevo} horas. "
            f"{formatTime(datetime.now(), nuevo)}."
        )
        self._finishLayer()

    @script(
        description="Dice si el anuncio de la hora está activado, cada cuánto se anuncia, qué motor de voz usa solo el reloj, qué voz usa el reloj, si el anuncio con grabaciones está activado y qué formato de hora se usa",
        category=CATEGORY,
        speakOnDemand=True,
    )
    def script_announceStatus(self, gesture) -> None:
        if self._get("anunciarCadaHora"):
            estado = f"activado, cada {self._intervalo()} minutos"
        else:
            estado = (
                f"desactivado, intervalo de {self._intervalo()} minutos"
            )
        if self._get("usarGrabaciones"):
            grabaciones = "activado"
        else:
            grabaciones = "desactivado"
        motor_reloj = self._clockSynthName()
        if motor_reloj:
            desc_motor = dict(getAvailableSynths()).get(motor_reloj, motor_reloj)
            motor = f"Motor del reloj: {desc_motor}. "
        else:
            _nombre, desc_actual = getCurrentSynth()
            motor = f"Motor del reloj: el de Tiresias ({desc_actual}). "
        self._say(
            f"Reloj. Anuncio de la hora {estado}. "
            f"{motor}"
            f"Voz del reloj: {self._getClockVoiceName()}. "
            f"Anuncio con grabaciones {grabaciones}. "
            f"Formato de {self._formato()} horas."
        )
        self._finishLayer()
