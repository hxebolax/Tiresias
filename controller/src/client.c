/*
tiresiasControllerClient.dll: biblioteca cliente de la API de control de
Tiresias para juegos y programas (32 y 64 bits).

Exporta las funciones tiresiasController_* y, con los mismos argumentos,
las nvdaController_* del "NVDA Controller Client". Por eso puede usarse
tal cual o renombrada como nvdaControllerClient.dll /
nvdaControllerClient32.dll / nvdaControllerClient64.dll en programas que ya
la usan (Tolk, SRAL, accessible_output2, mods de juegos...).

Cada llamada intenta primero el punto de conexión de Tiresias
("TiresiasCtlr.<sesión>.<escritorio>") y, si no hay nadie, el de NVDA
("NvdaCtlr.<sesión>.<escritorio>"): así funciona con Tiresias, con NVDA o
con cualquiera de los dos que esté en ejecución. Se recuerda el último que
respondió para no repetir el intento fallido.

Archivo escrito para Tiresias.
*/

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <rpc.h>
#include <stdio.h>
#include <stdlib.h>
#include "tiresiasController_rpc.h"
#include "../include/tiresiasControllerClient.h"

#define ENDPOINT_COUNT 2

static handle_t g_handles[ENDPOINT_COUNT] = {NULL, NULL};
static volatile LONG g_preferred = 0;
static INIT_ONCE g_initOnce = INIT_ONCE_STATIC_INIT;
static RPC_STATUS g_initStatus = RPC_S_OK;
static tiresiasController_markCallback g_markCallback = NULL;

void* __RPC_USER midl_user_allocate(size_t size) {
	return malloc(size);
}

void __RPC_USER midl_user_free(void* p) {
	free(p);
}

/* "<sesión>.<escritorio>" del hilo que llama (igual que el servidor). */
static void desktopNamespace(wchar_t* buf, size_t cch) {
	DWORD session = 0;
	wchar_t desk[64] = L"Default";
	HDESK hDesk;
	ProcessIdToSessionId(GetCurrentProcessId(), &session);
	hDesk = GetThreadDesktop(GetCurrentThreadId());
	if (hDesk) {
		DWORD needed = 0;
		if (!GetUserObjectInformationW(hDesk, UOI_NAME, desk, sizeof(desk), &needed)) {
			lstrcpynW(desk, L"Default", 64);
		}
	}
	_snwprintf_s(buf, cch, _TRUNCATE, L"%lu.%s", (unsigned long)session, desk);
}

static BOOL CALLBACK initBindings(PINIT_ONCE once, PVOID param, PVOID* ctx) {
	static const wchar_t* prefixes[ENDPOINT_COUNT] = {L"TiresiasCtlr.", L"NvdaCtlr."};
	wchar_t ns[96];
	wchar_t binding[200];
	int i;
	(void)once;
	(void)param;
	(void)ctx;
	desktopNamespace(ns, 96);
	for (i = 0; i < ENDPOINT_COUNT; i++) {
		RPC_STATUS st;
		_snwprintf_s(binding, 200, _TRUNCATE, L"ncalrpc:[%s%s]", prefixes[i], ns);
		st = RpcBindingFromStringBindingW((RPC_WSTR)binding, &g_handles[i]);
		if (st != RPC_S_OK) {
			g_handles[i] = NULL;
			g_initStatus = st;
		}
	}
	return TRUE;
}

static void ensureInit(void) {
	InitOnceExecuteOnce(&g_initOnce, initBindings, NULL, NULL);
}

/* Errores que indican que en ese punto de conexión no hay quien responda. */
static int isUnavailable(error_status_t st) {
	switch (st) {
	case RPC_S_SERVER_UNAVAILABLE:
	case EPT_S_NOT_REGISTERED:
	case RPC_S_UNKNOWN_IF:
	case RPC_S_CALL_FAILED_DNE:
	case RPC_S_INVALID_BINDING:
	case RPC_S_PROTSEQ_NOT_SUPPORTED:
	case RPC_S_SERVER_TOO_BUSY:
	case ERROR_SERVICE_NOT_ACTIVE:
		return 1;
	default:
		return 0;
	}
}

/* Ejecuta CALL con el manejador H, primero en el punto preferido. */
#define TRY_ENDPOINTS(CALL)                                                   \
	do {                                                                      \
		error_status_t _st = RPC_S_SERVER_UNAVAILABLE;                        \
		LONG _first;                                                          \
		int _n;                                                               \
		ensureInit();                                                         \
		_first = g_preferred;                                                 \
		for (_n = 0; _n < ENDPOINT_COUNT; _n++) {                             \
			LONG _idx = (_first + _n) % ENDPOINT_COUNT;                       \
			handle_t H = g_handles[_idx];                                     \
			if (!H) continue;                                                 \
			_st = (CALL);                                                     \
			if (!isUnavailable(_st)) {                                        \
				if (_idx != _first) InterlockedExchange(&g_preferred, _idx);  \
				return _st;                                                   \
			}                                                                 \
		}                                                                     \
		return _st;                                                           \
	} while (0)

/* Versión que solo se intenta en Tiresias (funciones propias). */
static error_status_t tiresiasOnly_speakTextEx(const wchar_t* text, unsigned long flags) {
	ensureInit();
	if (!g_handles[0]) {
		return RPC_S_SERVER_UNAVAILABLE;
	}
	return rpc_speakTextEx(g_handles[0], text, flags);
}

/* ------------------------------------------------------------ API */
error_status_t __stdcall tiresiasController_testIfRunning(void) {
	TRY_ENDPOINTS(rpc_testIfRunning(H));
}

error_status_t __stdcall tiresiasController_speakText(const wchar_t* text) {
	if (!text) return ERROR_INVALID_PARAMETER;
	TRY_ENDPOINTS(rpc_speakText(H, text));
}

error_status_t __stdcall tiresiasController_cancelSpeech(void) {
	TRY_ENDPOINTS(rpc_cancelSpeech(H));
}

error_status_t __stdcall tiresiasController_brailleMessage(const wchar_t* message) {
	if (!message) return ERROR_INVALID_PARAMETER;
	TRY_ENDPOINTS(rpc_brailleMessage(H, message));
}

error_status_t __stdcall tiresiasController_getProcessId(unsigned long* pid) {
	if (!pid) return ERROR_INVALID_PARAMETER;
	TRY_ENDPOINTS(rpc_getProcessId(H, pid));
}

error_status_t __stdcall tiresiasController_speakSsml(const wchar_t* ssml, SYMBOL_LEVEL symbolLevel, SPEECH_PRIORITY priority, boolean asynchronous) {
	if (!ssml) return ERROR_INVALID_PARAMETER;
	TRY_ENDPOINTS(rpc_speakSsml(H, ssml, symbolLevel, priority, asynchronous));
}

error_status_t __stdcall tiresiasController_isSpeaking(boolean* speaking) {
	if (!speaking) return ERROR_INVALID_PARAMETER;
	TRY_ENDPOINTS(rpc_isSpeaking(H, speaking));
}

error_status_t __stdcall tiresiasController_setOnSsmlMarkReachedCallback(tiresiasController_markCallback callback) {
	g_markCallback = callback;
	return ERROR_SUCCESS;
}

error_status_t __stdcall tiresiasController_getApiVersion(unsigned long* version) {
	error_status_t st;
	if (!version) return ERROR_INVALID_PARAMETER;
	ensureInit();
	if (!g_handles[0]) return RPC_S_SERVER_UNAVAILABLE;
	st = rpc_getApiVersion(g_handles[0], version);
	return st;
}

error_status_t __stdcall tiresiasController_speakTextEx(const wchar_t* text, unsigned long flags) {
	error_status_t st;
	if (!text) return ERROR_INVALID_PARAMETER;
	st = tiresiasOnly_speakTextEx(text, flags);
	if (!isUnavailable(st)) {
		return st;
	}
	/* Sin Tiresias (por ejemplo, solo NVDA): se aproxima con la API común. */
	if (flags & TIRESIAS_SPEAK_INTERRUPT) {
		tiresiasController_cancelSpeech();
	}
	if (flags & TIRESIAS_SPEAK_BRAILLE) {
		tiresiasController_brailleMessage(text);
	}
	return tiresiasController_speakText(text);
}

error_status_t __stdcall tiresiasController_pauseSpeech(boolean pause) {
	ensureInit();
	if (!g_handles[0]) return RPC_S_SERVER_UNAVAILABLE;
	return rpc_pauseSpeech(g_handles[0], pause);
}

/* Retrollamada del servidor durante speakSsml síncrono. */
error_status_t srv_onSsmlMarkReached(const wchar_t* mark) {
	tiresiasController_markCallback cb = g_markCallback;
	if (!cb) {
		return ERROR_CALL_NOT_IMPLEMENTED;
	}
	return cb(mark);
}

BOOL WINAPI DllMain(HINSTANCE hModule, DWORD reason, LPVOID reserved) {
	int i;
	(void)hModule;
	if (reason == DLL_PROCESS_ATTACH) {
		DisableThreadLibraryCalls(hModule);
	} else if (reason == DLL_PROCESS_DETACH && reserved == NULL) {
		for (i = 0; i < ENDPOINT_COUNT; i++) {
			if (g_handles[i]) {
				RpcBindingFree(&g_handles[i]);
			}
		}
	}
	return TRUE;
}
