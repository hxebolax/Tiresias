# API de control de Tiresias

Documento para desarrolladores de juegos, mods y programas que quieren hablar
o mostrar braille a través del lector de pantalla del usuario.

## Resumen

Tiresias atiende dos API por RPC local (`ncalrpc`), sin red:

1. **La del «NVDA Controller Client»**: `nvdaControllerClient.dll`,
   `nvdaControllerClient32.dll` / `nvdaControllerClient64.dll`, y las
   bibliotecas que la usan (Tolk, SRAL, accessible_output2, UniversalSpeech,
   UnityAccessibilityLib, mods como Hearthstone Access o Say the Spire...).
   **No hay que cambiar nada**: si Tiresias está en ejecución y NVDA no, esos
   programas hablan con Tiresias. Funciona aunque NVDA no esté instalado.
2. **La propia de Tiresias**: `tiresiasControllerClient.dll` (32 y 64 bits),
   con todo lo anterior más funciones propias. Esta biblioteca funciona
   también con NVDA: si Tiresias no está en ejecución, prueba con NVDA.

| Función | NVDA Controller | Tiresias | Notas |
|---|---|---|---|
| `testIfRunning()` | sí | sí | 0 si hay lector y acepta órdenes |
| `speakText(texto)` | sí | sí | se encola tras lo que se esté diciendo |
| `cancelSpeech()` | sí | sí | |
| `brailleMessage(texto)` | sí | sí | mensaje temporal en la línea braille |
| `getProcessId(&pid)` | sí (2.0) | sí | PID del lector |
| `speakSsml(ssml, nivel, prioridad, asíncrono)` | sí (2.0) | sí | con marcas `<mark>` |
| `setOnSsmlMarkReachedCallback(cb)` | sí (2.0) | sí | en el propio cliente |
| `isSpeaking(&hablando)` | sí (2026.3) | sí | |
| `getApiVersion(&versión)` | — | sí | `0xMMMMmmmm`; ahora `0x00010000` (1.0) |
| `speakTextEx(texto, opciones)` | — | sí | cortar la voz, deletrear, braille |
| `pauseSpeech(pausa)` | — | sí | pausa y reanuda (petición de NVDA #12945) |

Todas devuelven `error_status_t`: 0 si va bien; si no, un código de Windows o
de RPC. Los habituales:

- 1722 (`RPC_S_SERVER_UNAVAILABLE`): no hay ningún lector en ejecución.
- 1062 (`ERROR_SERVICE_NOT_ACTIVE`): Tiresias está abierto pero el usuario
  ha desactivado la API en Opciones › Programas externos.
- 120 (`ERROR_CALL_NOT_IMPLEMENTED`): función no disponible.

## Archivos

En la versión compilada están en `Tiresias\data\controller` (y este documento,
en `Tiresias\data\docs`):

```
data\controller\
  include\tiresiasControllerClient.h      cabecera C/C++
  x64\tiresiasControllerClient.dll/.lib   cliente de 64 bits
  x86\tiresiasControllerClient.dll/.lib   cliente de 32 bits
  x64\tiresiasControllerServer.dll        servidor (lo carga Tiresias)
  x64\tiresiasNvdaWindow.exe              auxiliar de compatibilidad con NVDA (ver abajo)
  examples\ejemplo.c, ejemplo.py          ejemplos
```

En el código fuente, los binarios (`x64`, `x86`) están en `data\controller` y
el resto en `controller\` (`include`, `examples`, y `src` con el IDL, el C y
los `.def`); `controller\build.py` compila y deja los binarios en
`data\controller`.

Distribuye con tu programa la `tiresiasControllerClient.dll` de la misma
arquitectura que tu ejecutable. No necesita los runtimes de Visual C++.

La DLL exporta también las funciones con el prefijo `nvdaController_`: puedes
renombrarla como `nvdaControllerClient.dll` (o `...32.dll` / `...64.dll`) y
usarla en lugar de la de NVDA; seguirá funcionando con NVDA y además con
Tiresias.

## Uso desde C/C++

```c
#include "tiresiasControllerClient.h"   // enlaza con tiresiasControllerClient.lib

if (tiresiasController_testIfRunning() == 0) {
	tiresiasController_speakText(L"Partida guardada");
	tiresiasController_speakTextEx(L"Vida baja", TIRESIAS_SPEAK_INTERRUPT | TIRESIAS_SPEAK_BRAILLE);
}
```

Opciones de `speakTextEx` (se combinan con `|`):

| Constante | Valor | Efecto |
|---|---|---|
| `TIRESIAS_SPEAK_INTERRUPT` | 0x1 | corta lo que se esté diciendo antes de hablar |
| `TIRESIAS_SPEAK_SPELL` | 0x2 | deletrea el texto (útil para caracteres sueltos) |
| `TIRESIAS_SPEAK_BRAILLE` | 0x4 | muestra también el texto en braille |

Con NVDA (sin Tiresias), `speakTextEx` se aproxima: corta la voz con
`cancelSpeech` si se pide y llama a `speakText`; `pauseSpeech` y
`getApiVersion` devuelven 1722.

## Uso desde otros lenguajes

Cualquier lenguaje que llame a funciones de una DLL con convención
`__stdcall` (ctypes en Python, P/Invoke en C#, `ffi` en Rust, Lua, Node...).
Ejemplo en Python: `controller\examples\ejemplo.py`.

C#:

```csharp
[DllImport("tiresiasControllerClient.dll", CharSet = CharSet.Unicode)]
static extern int tiresiasController_speakText(string text);
[DllImport("tiresiasControllerClient.dll", CharSet = CharSet.Unicode)]
static extern int tiresiasController_speakTextEx(string text, uint flags);
```

## SSML

`speakSsml` admite: `speak`, `p`, `s`, `break` (`time="500ms"`, `"1s"` o
`strength`), `mark name`, `prosody` (`pitch`, `rate`, `volume` en porcentaje,
relativo `+20%`/`-20%`, número o palabras como `high`/`fast`), `voice`/`lang`/
`xml:lang` (cambio de idioma), `say-as interpret-as="characters"` (deletreo),
`sub alias`, `phoneme ph` (IPA) y `emphasis`. Lo desconocido se lee como
texto. Si el SSML no es XML válido se quitan las etiquetas.

- **Nivel de símbolos**: -1 (el del usuario), 0, 100, 200, 300 o 1000.
- **Prioridad**: 0 normal, 1 siguiente, 2 ahora (pasa por delante).
- **Síncrono** (`asynchronous = FALSE`): la llamada vuelve cuando termina la
  voz (o se corta), y por cada `<mark name="x"/>` alcanzada se llama a la
  función fijada con `setOnSsmlMarkReachedCallback`, en el hilo de la llamada.
  Máximo 120 segundos.

## Cómo encuentra el cliente al lector

El punto de conexión depende de la sesión de Windows y del escritorio del
hilo que llama: `ncalrpc:[TiresiasCtlr.<sesión>.<escritorio>]` (el propio de
Tiresias) y `ncalrpc:[NvdaCtlr.<sesión>.<escritorio>]` (el de NVDA, por
ejemplo `NvdaCtlr.1.Default`). El cliente de Tiresias prueba los dos y
recuerda el último que respondió.

Tiresias nunca ocupa el de NVDA mientras NVDA está en ejecución: los
programas con `nvdaControllerClient` siguen hablando con NVDA. Cuando NVDA
no está, lo atiende el auxiliar `tiresiasNvdaWindow.exe` (ver abajo), que se
cierra en cuanto NVDA arranca para dejárselo libre.

### Punto de conexión de NVDA y ventana de compatibilidad «NVDA»

Un proceso **no puede soltar un punto de conexión ncalrpc sin terminar**:
`RpcServerUseProtseqEp` no tiene operación inversa, `RpcServerUnregisterIf`
solo quita las interfaces, `RpcMgmtStopServerListening` solo deja de
atender (el puerto ALPC sigue abierto y otro proceso que intente usar el
mismo nombre recibe `RPC_S_DUPLICATE_ENDPOINT`, 1740) y `RpcEpUnregister`
solo afecta al asignador de puntos de conexión, que ncalrpc con nombre fijo
no usa. Se comprobó con una prueba: tras `RpcMgmtStopServerListening` y
`RpcMgmtWaitServerListen`, otro proceso sigue sin poder abrir el punto.

Y NVDA necesita ese punto libre: al arrancar, si otro proceso lo tiene, NVDA
ignora el error y se queda sin él (sus propios componentes dentro de las
aplicaciones tampoco podrían hablar con él). Por eso Tiresias no lo abre en
su proceso, sino en el auxiliar `tiresiasNvdaWindow.exe`, que:

- atiende `NvdaCtlr.<sesión>.<escritorio>` y reenvía cada llamada a
  Tiresias por una interfaz privada (`TiresiasRelay`, en
  `controller\src\tiresiasRelay.idl`) con el proceso que llamó (Tiresias
  solo acepta el reenvío de su propio auxiliar; las marcas de `speakSsml`
  síncrono vuelven al programa);
- crea, si está activada la opción «Crear la ventana de identificación de
  NVDA», la ventana oculta de clase `wxWindowClassNR` y título `NVDA` que
  algunas bibliotecas (Tolk, la más usada en audiojuegos) buscan antes de
  usar `nvdaControllerClient`.

NVDA, al arrancar, cierra el proceso dueño de esa ventana: se cierra el
auxiliar y el punto de conexión queda libre al instante. Además Tiresias
vigila cada segundo si aparece `nvda.exe` y cierra el auxiliar en cuanto lo
ve (necesario si la ventana está desactivada). Cuando NVDA se cierra,
Tiresias vuelve a iniciar el auxiliar.

Si Tiresias está en espera porque otro lector de pantalla tiene preferencia
(ver el manual, «Convivencia con otros lectores de pantalla»), no hay
auxiliar y el punto propio de Tiresias responde 1062 a todo: el cliente de
Tiresias pasa solo al de NVDA y las bibliotecas como Tolk eligen el lector
que está activo.

## Opciones del usuario (Opciones › Programas externos)

- Permitir que los programas hablen a través de Tiresias (si no, se responde
  1062 y las bibliotecas pasan a otro lector o a SAPI).
- Atender también a los programas hechos para NVDA.
- Crear la ventana de identificación de NVDA.
- Cortar la voz con cada texto nuevo de un programa.
- Mostrar en braille los textos que se mandan hablar.
- Mostrar los mensajes braille de los programas.
- Atender solo al programa en primer plano (para que un juego en segundo
  plano no hable).

Además, la orden «Silenciar o reactivar los programas externos»
(Tiresias+Mayúsculas+Alt+G) calla temporalmente a todos los programas sin
que estos reciban error. Lo que dicen los programas queda en el historial de
voz con el origen «Programas externos».

## Compilar las bibliotecas

Requisitos: Visual Studio con las herramientas de C++ y el SDK de Windows
(MIDL).

```
python controller\build.py          (x64 y x86)
python controller\build.py x64
```

El contrato RPC está en `controller\src\tiresiasController.idl`. Las tres
primeras interfaces reproducen el contrato público del NVDA Controller Client
(mismos identificadores, mismo orden de procedimientos y mismos tipos en la
red); la cuarta, `TiresiasController`
(`6B1C9E52-3F0A-4D7B-9C1E-7A54D2E8B310`), es la propia.

## Probado con

- `nvdaControllerClient` oficiales de 64 y 32 bits, antiguos (solo
  speakText, cancelSpeech, brailleMessage y testIfRunning) y actuales (con
  getProcessId y speakSsml con marcas).
- `tiresiasControllerClient.dll` de 64 y 32 bits, también renombrada como
  nvdaControllerClient.
- Tolk (detecta «NVDA» y habla por Tiresias gracias a la ventana de
  compatibilidad).
