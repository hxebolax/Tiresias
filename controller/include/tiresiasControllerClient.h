/*
tiresiasControllerClient.h: API de control de Tiresias para programas y juegos.

Enlaza con tiresiasControllerClient.lib (o carga tiresiasControllerClient.dll
con LoadLibrary). Todas las funciones devuelven 0 (ERROR_SUCCESS) si van bien
o un código de error de Windows/RPC (por ejemplo 1722,
RPC_S_SERVER_UNAVAILABLE, si no hay ningún lector en ejecución).

La biblioteca también exporta las mismas funciones con el prefijo
nvdaController_ (compatibles con el "NVDA Controller Client"), y funciona
tanto con Tiresias como con NVDA. Documentación: docs/api_control.md.
*/

#ifndef TIRESIAS_CONTROLLER_CLIENT_H
#define TIRESIAS_CONTROLLER_CLIENT_H

#include <windows.h>
#include <rpc.h>

#ifdef __cplusplus
extern "C" {
#endif

#ifndef __tiresiasController_rpc_h__
/* Prioridad de speakSsml. */
typedef enum tagSPEECH_PRIORITY {
	SPEECH_PRIORITY_NORMAL = 0, /* se encola */
	SPEECH_PRIORITY_NEXT = 1,   /* se encola */
	SPEECH_PRIORITY_NOW = 2     /* corta lo que se esté diciendo */
} SPEECH_PRIORITY;

/* Nivel de símbolos de speakSsml. */
typedef enum tagSYMBOL_LEVEL {
	SYMBOL_LEVEL_NONE = 0,
	SYMBOL_LEVEL_SOME = 100,
	SYMBOL_LEVEL_MOST = 200,
	SYMBOL_LEVEL_ALL = 300,
	SYMBOL_LEVEL_CHAR = 1000,
	SYMBOL_LEVEL_UNCHANGED = -1 /* el que tenga configurado el usuario */
} SYMBOL_LEVEL;
#endif

/* Opciones de tiresiasController_speakTextEx (se pueden combinar con |). */
#define TIRESIAS_SPEAK_INTERRUPT 0x00000001UL /* corta la voz antes de hablar */
#define TIRESIAS_SPEAK_SPELL     0x00000002UL /* deletrea el texto */
#define TIRESIAS_SPEAK_BRAILLE   0x00000004UL /* además lo muestra en braille */

/* Versión de la API (tiresiasController_getApiVersion): 0xMMMMmmmm. */
#define TIRESIAS_CONTROLLER_API_VERSION 0x00010000UL

/* Retrollamada de las marcas <mark name="..."/> de speakSsml síncrono. */
typedef error_status_t (__stdcall *tiresiasController_markCallback)(const wchar_t* mark);

#ifdef TIRESIAS_CONTROLLER_BUILD
#define TIRESIAS_CONTROLLER_API
#else
#define TIRESIAS_CONTROLLER_API __declspec(dllimport)
#endif

/* 0 si Tiresias (o NVDA) está en ejecución y acepta órdenes. */
TIRESIAS_CONTROLLER_API error_status_t __stdcall tiresiasController_testIfRunning(void);
/* Habla un texto; se encola tras lo que se esté diciendo. */
TIRESIAS_CONTROLLER_API error_status_t __stdcall tiresiasController_speakText(const wchar_t* text);
/* Corta la voz. */
TIRESIAS_CONTROLLER_API error_status_t __stdcall tiresiasController_cancelSpeech(void);
/* Muestra un mensaje temporal en la línea braille. */
TIRESIAS_CONTROLLER_API error_status_t __stdcall tiresiasController_brailleMessage(const wchar_t* message);
/* Identificador del proceso del lector. */
TIRESIAS_CONTROLLER_API error_status_t __stdcall tiresiasController_getProcessId(unsigned long* pid);
/* Habla SSML. Con asynchronous = FALSE espera a que termine y avisa de las marcas. */
TIRESIAS_CONTROLLER_API error_status_t __stdcall tiresiasController_speakSsml(const wchar_t* ssml, SYMBOL_LEVEL symbolLevel, SPEECH_PRIORITY priority, boolean asynchronous);
/* Fija la retrollamada de las marcas SSML (NULL para quitarla). */
TIRESIAS_CONTROLLER_API error_status_t __stdcall tiresiasController_setOnSsmlMarkReachedCallback(tiresiasController_markCallback callback);
/* Indica si el lector está hablando. */
TIRESIAS_CONTROLLER_API error_status_t __stdcall tiresiasController_isSpeaking(boolean* speaking);

/* Solo Tiresias: */
/* Versión de la API del lector en ejecución. */
TIRESIAS_CONTROLLER_API error_status_t __stdcall tiresiasController_getApiVersion(unsigned long* version);
/* Habla con opciones TIRESIAS_SPEAK_*. Con NVDA se aproxima con speakText. */
TIRESIAS_CONTROLLER_API error_status_t __stdcall tiresiasController_speakTextEx(const wchar_t* text, unsigned long flags);
/* Pausa (TRUE) o reanuda (FALSE) la voz. */
TIRESIAS_CONTROLLER_API error_status_t __stdcall tiresiasController_pauseSpeech(boolean pause);

#ifdef __cplusplus
}
#endif

#endif /* TIRESIAS_CONTROLLER_CLIENT_H */
