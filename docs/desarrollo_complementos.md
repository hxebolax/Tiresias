# Guía de desarrollo de complementos para Tiresias

Un complemento amplía Tiresias sin tocar su código: módulos de aplicación,
complementos globales, sintetizadores y controladores braille.

## 1. Estructura

```
data/addons/miComplemento/
	manifest.json
	appModules/              <proceso>.py (p. ej. notepad.py, whatsapp_root.py)
	globalPlugins/           cualquier .py o paquete con clase GlobalPlugin
	synthDrivers/            <nombre>.py con clase SynthDriver
	brailleDisplayDrivers/   <nombre>.py con clase BrailleDisplayDriver
	doc/es/readme.html       ayuda (se abre desde el administrador)
	installTasks.py          onInstall() / onUninstall() opcionales
```

Los archivos que empiezan por `_` no se cargan automáticamente (sirven como
módulos auxiliares que se importan con `from . import _miModulo`).

`manifest.json`:

```json
{
	"id": "miComplemento",
	"name": "Mi complemento",
	"version": "1.0.0",
	"author": "Nombre <correo>",
	"description": "Qué hace el complemento",
	"minApiVersion": "1.0",
	"lastTestedApiVersion": "1.0",
	"url": ""
}
```

Para distribuirlo: `Tiresias.bat complementos` genera
`dist\complementos\<id>.tiresias-addon` (un ZIP). El usuario lo instala desde
*Complementos > Administrador de complementos > Instalar desde archivo...*.
El paquete se llama como el `id` del manifiesto. `manifest.json` puede
llevar BOM (el Bloc de notas lo guarda así).

Durante el desarrollo basta con copiar la carpeta en `data/addons` y pulsar
**Tiresias+Control+F3** para recargar.

## 2. Módulo de aplicación

El nombre del archivo es el del ejecutable en minúsculas, sin extensión y con
los puntos cambiados por guiones bajos (`WhatsApp.Root.exe` → `whatsapp_root.py`).

```python
from tiresias import speech, api
from tiresias.appmodules import AppModule as BaseAppModule
from tiresias.baseobject import script


class AppModule(BaseAppModule):
	# Desactiva el modo exploración en documentos web de esta aplicación.
	disableBrowseModeByDefault = True

	@script(description="Dice el título de la ventana", gesture="kb:alt+t", category="Mi aplicación")
	def script_titulo(self, gesture):
		fg = api.getForegroundObject()
		speech.speakMessage(fg.name if fg else "sin título")

	def event_gainFocus(self, obj, nextHandler):
		# Se puede decir algo antes o en lugar de lo normal.
		nextHandler()

	def chooseObjectClass(self, obj, clsList):
		# Añade comportamiento a ciertos objetos (ver sección 4).
		if getattr(obj, "UIAAutomationId", "") == "ListaMensajes":
			clsList.insert(0, MiLista)
```

Eventos disponibles (todos con la firma `event_x(self, obj, nextHandler, **kw)`):
`gainFocus`, `loseFocus`, `foreground`, `focusEntered`, `nameChange`,
`valueChange`, `stateChange`, `descriptionChange`, `caret`, `textChange`,
`liveRegionChange`, `notification` (con `displayString`), `alert`,
`tooltipOpen`, `menuStart`, `menuEnd`, `windowOpened`, `selection`,
`typedCharacter` (con `ch`), `documentLoadComplete`, `itemStatusChange`.
Además `event_appModule_gainFocus(self)` y `event_appModule_loseFocus(self)`.

## 3. Complemento global

```python
from tiresias import speech
from tiresias.baseobject import script
from tiresias.plugins import GlobalPlugin as BaseGlobalPlugin


class GlobalPlugin(BaseGlobalPlugin):
	@script(description="Saluda", gesture="kb:tiresias+shift+g", category="Ejemplo")
	def script_saludar(self, gesture):
		speech.speakMessage("¡Hola!")

	def terminate(self):
		pass
```

## 4. Clases superpuestas (overlay)

Los objetos son clases dinámicas: el objeto UIA base más las clases que
añadan los módulos. Así se cambian propiedades o se añaden órdenes a tipos
concretos de control:

```python
from tiresias.objects.base import AccObject
from tiresias.objects.roles import Role
from tiresias.baseobject import script


class MiLista(AccObject):
	def _get_name(self):
		# Quita ruido del nombre original.
		return super()._get_name().replace("Elemento:", "")

	@script(description="Lee la fecha del elemento", gesture="kb:alt+f")
	def script_fecha(self, gesture):
		...
```

Propiedades útiles de los objetos: `name`, `role`, `states`, `value`,
`description`, `location`, `parent`, `next`, `previous`, `firstChild`,
`children`, `processID`, `appModule`, `windowHandle`, `positionInfo`,
`makeTextInfo(posición)`. En objetos UIA además: `element`
(`IUIAutomationElement`), `UIAAutomationId`, `UIAClassName`, `UIAControlType`,
`UIAAriaRole`, `UIAAriaProperties`, `doAction()`, `setFocus()`,
`scrollIntoView()`, `expandCollapse()`, `setValue()`.

## 5. Gestos

Formato: `kb:` + modificadores (`tiresias`, `control`, `shift`, `alt`,
`windows`) + tecla, separados por `+`. Ejemplos: `kb:tiresias+f12`,
`kb:control+shift+enter`, `kb(laptop):tiresias+l`, `kb:numpad8`,
`kb:alt+upArrow`. Los nombres de teclas están en `tiresias/input/keys.py`.

Para reenviar la tecla a la aplicación desde una orden: `gesture.send()`.
Para enviar otra combinación: `from tiresias.input.gestures import sendKey;
sendKey("control+shift+m")`.

## 6. Configuración del complemento

```python
from tiresias.config import conf

conf.registerDefaults("miComplemento", {"activo": True, "nivel": 3})
if conf["miComplemento"]["activo"]:
	...
conf["miComplemento"]["nivel"] = 5   # se guarda con la configuración
```

Para añadir un panel en el cuadro de Opciones:
`from tiresias.gui import settings; settings.registerPanel("miId", "Mi complemento", MiPanel)`
donde `MiPanel` hereda de `settings.SettingsPanel`. Las categorías de los
complementos aparecen en la lista detrás de «Aplicaciones» (y antes de «Avanzado»).

## 6 bis. Cambiar lo que presenta el modo exploración

El búfer virtual de las páginas web (`tiresias.browse.buffer.VirtualBuffer`)
ofrece el punto de extensión `filter_node`: un filtro que recibe cada `Node`
en el momento de crearlo, antes de recorrer sus hijos y de emitir su texto.
Sirve para arreglar lo que una página presenta mal **sin tocar la página**
(nombres, roles, niveles de encabezado, regiones, tablas de maquetación) o
para quitar elementos:

```python
from tiresias.browse import buffer as vbuf
from tiresias.browse.flexweb import siteKey
from tiresias.objects.roles import Role, State


class GlobalPlugin(BaseGlobalPlugin):
	def __init__(self):
		super().__init__()
		vbuf.filter_node.register(self.filtrarNodo)

	def terminate(self):
		vbuf.filter_node.unregister(self.filtrarNodo)

	def filtrarNodo(self, value, buffer, controlType):
		# value: el Node (o None si otro manejador lo quitó: devuélvelo tal cual).
		# buffer.documentKey: dirección del documento (siteKey() da el sitio).
		# controlType: tipo de control UIA (uc.CT_GROUP, uc.CT_HYPERLINK...).
		if value is None or siteKey(buffer.documentKey) != "www.ejemplo.com":
			return value
		if value.automationId == "anuncio":
			return None                      # fuera del búfer, con sus descendientes
		if value.clickable and value.role == Role.GROUPING:
			value.role = Role.BUTTON         # se presenta y se activa como botón
			value.clickable = False
			value.states.discard(State.CLICKABLE)
		return value
```

Reglas:

- Se llama en el **hilo que construye el búfer** (no en el núcleo), una vez
  por nodo y también en las actualizaciones parciales: tiene que ser rápido
  (una búsqueda en un diccionario) y no debe tocar la interfaz.
- El nodo tiene `parent` y los hermanos anteriores ya están en
  `parent.children`, pero **no tiene hijos ni texto** todavía: lo que se
  decida se basa en `role`, `name`, `automationId`, `className`, `ariaRole`,
  `lct`, `url`, `aria`, `location` y los antecesores.
- Cambiar `role` surte efecto en el recorrido: los roles atómicos (botones,
  campos) emiten su `name` y no recorren hijos; un encabezado o una región
  recorre los suyos y se anuncia con su prefijo.
- Para que el documento se reconstruya conservando la posición tras cambiar
  tus reglas, llama a `doc.requestRebuild()` (en el núcleo) sobre el
  documento (`tiresias.ai.assistant.currentBrowseDocument()` da el actual).

El complemento de tienda **Arreglo web** (`complementos_tienda/arregloWeb`)
es el ejemplo completo: analiza la página (`analisis.py`), guarda reglas por
sitio (`almacen.py`) y las aplica con este filtro (`arreglos.py`).

## 7. Sintetizadores

```python
from tiresias.synth.base import AudioSynthDriver, VoiceSetting, RateSetting, VoiceInfo


class SynthDriver(AudioSynthDriver):
	name = "miVoz"            # igual que el nombre del archivo
	description = "Mi voz"
	sampleRate = 22050
	supportedSettings = (VoiceSetting(), RateSetting())

	@classmethod
	def check(cls):
		return True           # ¿se puede usar en este equipo?

	def _getAvailable_voice(self):
		from collections import OrderedDict
		return OrderedDict({"v1": VoiceInfo("v1", "Voz 1", "es_ES")})

	def _synthesizeSegment(self, items, emit, isCancelled):
		# items: cadenas y órdenes (PitchCommand, BreakCommand...)
		texto = "".join(i for i in items if isinstance(i, str))
		emit(generar_pcm_16_bits_mono(texto))
```

El complemento **Eloquence** (`data/addons/eloquence`) es un ejemplo completo
de sintetizador que usa un proceso auxiliar de 32 bits. No está en el
repositorio público (incluye bibliotecas propietarias): se instala desde la
tienda de complementos. En el repositorio, el complemento **Voces neuronales
de Microsoft** (`complementos_tienda/NeuralVoices`) es otro ejemplo de
sintetizador.

## 8. Controladores braille

```python
from tiresias.braille import BrailleDisplayDriver


class BrailleDisplayDriver(BrailleDisplayDriver):
	name = "miLinea"
	description = "Mi línea braille"
	numCells = 40

	@classmethod
	def check(cls):
		return True

	def display(self, cells):
		# cells: lista de enteros (bit 0 = punto 1 ... bit 7 = punto 8)
		...
```

## 9. Buenas prácticas

- No bloquees el hilo del núcleo más de unos milisegundos; usa
  `queue_handler.callLater` para trabajos periódicos.
- Localiza elementos por identificadores estables (`AutomationId`, roles
  ARIA, clases estables) antes que por textos; si usas textos, ponlos en
  tablas por idioma.
- Para recorrer subárboles grandes usa una única petición de caché
  (ver `snapshot()` en el complemento de WhatsApp).
- Todo texto visible en español y envuelto en `_()` si es parte del núcleo.
