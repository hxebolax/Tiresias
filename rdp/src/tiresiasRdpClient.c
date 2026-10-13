/*
 * tiresiasRdpClient.dll: complemento de canal virtual dinámico para el
 * cliente de Escritorio remoto (mstsc.exe).
 *
 * El cliente de Escritorio remoto carga esta biblioteca porque está
 * registrada en HKCU\Software\Microsoft\Terminal Server Client\Default\AddIns.
 * Al iniciar una conexión, el complemento escucha el canal dinámico
 * «TiresiasRdp». Cuando el Tiresias que se ejecuta dentro de la sesión remota
 * abre ese canal, la biblioteca lo une con el Tiresias local mediante la
 * tubería con nombre \\.\pipe\TiresiasRdp.<sesión> (la sesión de Windows del
 * propio mstsc.exe):
 *
 *   canal -> tubería: voz, cancelaciones, sonidos y celdas braille.
 *   tubería -> canal: tamaño de la línea braille local y sus teclas.
 *
 * La biblioteca no interpreta los mensajes (JSON por líneas): solo copia
 * bytes en los dos sentidos. Si Tiresias no está en marcha, lo que llega del
 * canal se descarta y se reintenta la conexión con la tubería cada segundo.
 *
 * Código propio del proyecto Tiresias.
 */

#define WIN32_LEAN_AND_MEAN
#define CINTERFACE
#include <windows.h>
#include <objbase.h>
#include <oleauto.h>
#include <tsvirtualchannels.h>
#include <strsafe.h>

/* {8E634465-D682-43F3-8342-0381D3C85B3E} */
static const CLSID CLSID_TiresiasRdpPlugin = {0x8e634465, 0xd682, 0x43f3, {0x83, 0x42, 0x03, 0x81, 0xd3, 0xc8, 0x5b, 0x3e}};

#define TRDP_CHANNEL_NAME "TiresiasRdp"
#define TRDP_PIPE_PREFIX L"\\\\.\\pipe\\TiresiasRdp."
#define TRDP_READ_BUFFER 65536
#define TRDP_WRITE_TIMEOUT 2000
#define TRDP_RETRY_MS 1000

static volatile LONG g_objects = 0;
static volatile LONG g_locks = 0;
static HMODULE g_module = NULL;

/* ================================================================ utilidades */
static void trdpLog(const wchar_t *fmt, ...)
{
	wchar_t buf[512];
	va_list args;
	va_start(args, fmt);
	if (SUCCEEDED(StringCchVPrintfW(buf, ARRAYSIZE(buf), fmt, args)))
	{
		OutputDebugStringW(buf);
	}
	va_end(args);
}

static void trdpPipeName(wchar_t *out, size_t count)
{
	DWORD session = 0;
	if (!ProcessIdToSessionId(GetCurrentProcessId(), &session))
	{
		session = 0;
	}
	StringCchPrintfW(out, count, L"%s%lu", TRDP_PIPE_PREFIX, session);
}

/* ================================================================ puente canal <-> tubería */
typedef struct TrdpBridge
{
	IWTSVirtualChannelCallback iface;
	volatile LONG refs;
	IWTSVirtualChannel *channel;
	CRITICAL_SECTION lock;      /* protege pipe */
	HANDLE pipe;                /* INVALID_HANDLE_VALUE si no hay conexión */
	HANDLE writeEvent;
	HANDLE stopEvent;
	HANDLE thread;
	volatile LONG closed;
} TrdpBridge;

static IWTSVirtualChannelCallbackVtbl g_bridgeVtbl;

static TrdpBridge *bridgeFrom(IWTSVirtualChannelCallback *p)
{
	return (TrdpBridge *)p;
}

static void bridgeDestroy(TrdpBridge *b)
{
	if (b->channel)
	{
		b->channel->lpVtbl->Release(b->channel);
	}
	if (b->pipe != INVALID_HANDLE_VALUE)
	{
		CloseHandle(b->pipe);
	}
	if (b->writeEvent)
	{
		CloseHandle(b->writeEvent);
	}
	if (b->stopEvent)
	{
		CloseHandle(b->stopEvent);
	}
	if (b->thread)
	{
		CloseHandle(b->thread);
	}
	DeleteCriticalSection(&b->lock);
	HeapFree(GetProcessHeap(), 0, b);
	InterlockedDecrement(&g_objects);
}

static HRESULT STDMETHODCALLTYPE bridge_QueryInterface(IWTSVirtualChannelCallback *This, REFIID riid, void **ppv)
{
	if (!ppv)
	{
		return E_POINTER;
	}
	if (IsEqualIID(riid, &IID_IUnknown) || IsEqualIID(riid, &IID_IWTSVirtualChannelCallback))
	{
		*ppv = This;
		This->lpVtbl->AddRef(This);
		return S_OK;
	}
	*ppv = NULL;
	return E_NOINTERFACE;
}

static ULONG STDMETHODCALLTYPE bridge_AddRef(IWTSVirtualChannelCallback *This)
{
	return (ULONG)InterlockedIncrement(&bridgeFrom(This)->refs);
}

static ULONG STDMETHODCALLTYPE bridge_Release(IWTSVirtualChannelCallback *This)
{
	TrdpBridge *b = bridgeFrom(This);
	LONG r = InterlockedDecrement(&b->refs);
	if (r == 0)
	{
		bridgeDestroy(b);
	}
	return (ULONG)r;
}

/* Cierra la tubería (con el cerrojo tomado). */
static void bridgeClosePipeLocked(TrdpBridge *b)
{
	if (b->pipe != INVALID_HANDLE_VALUE)
	{
		CancelIoEx(b->pipe, NULL);
		CloseHandle(b->pipe);
		b->pipe = INVALID_HANDLE_VALUE;
	}
}

/* Datos que llegan del equipo remoto: se copian en la tubería. */
static HRESULT STDMETHODCALLTYPE bridge_OnDataReceived(IWTSVirtualChannelCallback *This, ULONG cbSize, BYTE *pBuffer)
{
	TrdpBridge *b = bridgeFrom(This);
	ULONG done = 0;
	if (!pBuffer || cbSize == 0)
	{
		return S_OK;
	}
	EnterCriticalSection(&b->lock);
	while (b->pipe != INVALID_HANDLE_VALUE && done < cbSize)
	{
		OVERLAPPED ov;
		DWORD written = 0;
		BOOL ok;
		ZeroMemory(&ov, sizeof(ov));
		ov.hEvent = b->writeEvent;
		ResetEvent(b->writeEvent);
		ok = WriteFile(b->pipe, pBuffer + done, cbSize - done, NULL, &ov);
		if (!ok && GetLastError() != ERROR_IO_PENDING)
		{
			trdpLog(L"TiresiasRdp: error %lu al escribir en la tubería", GetLastError());
			bridgeClosePipeLocked(b);
			break;
		}
		if (WaitForSingleObject(b->writeEvent, TRDP_WRITE_TIMEOUT) != WAIT_OBJECT_0)
		{
			/* Tiresias no lee: se abandona la conexión y se volverá a intentar. */
			trdpLog(L"TiresiasRdp: la tubería no responde");
			CancelIoEx(b->pipe, &ov);
			GetOverlappedResult(b->pipe, &ov, &written, TRUE);
			bridgeClosePipeLocked(b);
			break;
		}
		if (!GetOverlappedResult(b->pipe, &ov, &written, FALSE))
		{
			bridgeClosePipeLocked(b);
			break;
		}
		done += written;
	}
	LeaveCriticalSection(&b->lock);
	return S_OK;
}

static HRESULT STDMETHODCALLTYPE bridge_OnClose(IWTSVirtualChannelCallback *This)
{
	TrdpBridge *b = bridgeFrom(This);
	HANDLE thread = NULL;
	if (InterlockedExchange(&b->closed, 1))
	{
		return S_OK;
	}
	SetEvent(b->stopEvent);
	EnterCriticalSection(&b->lock);
	bridgeClosePipeLocked(b);
	thread = b->thread;
	LeaveCriticalSection(&b->lock);
	if (thread && GetThreadId(thread) != GetCurrentThreadId())
	{
		WaitForSingleObject(thread, 5000);
	}
	return S_OK;
}

static IWTSVirtualChannelCallbackVtbl g_bridgeVtbl = {
	bridge_QueryInterface,
	bridge_AddRef,
	bridge_Release,
	bridge_OnDataReceived,
	bridge_OnClose,
};

/* Intenta conectar con la tubería de Tiresias. */
static HANDLE bridgeOpenPipe(void)
{
	wchar_t name[128];
	HANDLE h;
	trdpPipeName(name, ARRAYSIZE(name));
	h = CreateFileW(name, GENERIC_READ | GENERIC_WRITE, 0, NULL, OPEN_EXISTING, FILE_FLAG_OVERLAPPED | SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION, NULL);
	if (h == INVALID_HANDLE_VALUE && GetLastError() == ERROR_PIPE_BUSY)
	{
		if (WaitNamedPipeW(name, 500))
		{
			h = CreateFileW(name, GENERIC_READ | GENERIC_WRITE, 0, NULL, OPEN_EXISTING, FILE_FLAG_OVERLAPPED | SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION, NULL);
		}
	}
	return h;
}

/* Avisa al equipo remoto de que el Tiresias local ya no escucha (mensaje
 * «client_left» del protocolo de acceso remoto): deja de enviar y, si lo
 * tenía silenciado, vuelve a hablar por su cuenta. El salto de línea inicial
 * termina cualquier línea que hubiera quedado a medias. */
static const char TRDP_DETACHED[] = "\n{\"type\":\"client_left\",\"client\":{\"id\":\"rdp\",\"connection_type\":\"master\"}}\n";

static void bridgeNotifyDetached(TrdpBridge *b)
{
	if (!b->closed && b->channel)
	{
		b->channel->lpVtbl->Write(b->channel, (ULONG)(sizeof(TRDP_DETACHED) - 1), (BYTE *)TRDP_DETACHED, NULL);
	}
	trdpLog(L"TiresiasRdp: Tiresias se ha desconectado de la tubería");
}

/* Hilo: conecta con la tubería y copia lo que llega de Tiresias al canal. */
static DWORD WINAPI bridgeThread(LPVOID param)
{
	TrdpBridge *b = (TrdpBridge *)param;
	BYTE *buffer = (BYTE *)HeapAlloc(GetProcessHeap(), 0, TRDP_READ_BUFFER);
	HANDLE readEvent = CreateEventW(NULL, TRUE, FALSE, NULL);
	HRESULT hrCom = CoInitializeEx(NULL, COINIT_MULTITHREADED);
	BOOL attached = FALSE;
	if (!buffer || !readEvent)
	{
		goto done;
	}
	while (WaitForSingleObject(b->stopEvent, 0) != WAIT_OBJECT_0)
	{
		HANDLE pipe;
		EnterCriticalSection(&b->lock);
		pipe = b->pipe;
		LeaveCriticalSection(&b->lock);
		if (pipe == INVALID_HANDLE_VALUE)
		{
			HANDLE h;
			if (attached)
			{
				attached = FALSE;
				bridgeNotifyDetached(b);
			}
			h = bridgeOpenPipe();
			if (h == INVALID_HANDLE_VALUE)
			{
				WaitForSingleObject(b->stopEvent, TRDP_RETRY_MS);
				continue;
			}
			EnterCriticalSection(&b->lock);
			if (b->closed)
			{
				CloseHandle(h);
				LeaveCriticalSection(&b->lock);
				break;
			}
			b->pipe = h;
			pipe = h;
			attached = TRUE;
			LeaveCriticalSection(&b->lock);
			trdpLog(L"TiresiasRdp: conectado con Tiresias");
		}
		{
			OVERLAPPED ov;
			HANDLE waits[2];
			DWORD got = 0;
			DWORD w;
			BOOL ok;
			ZeroMemory(&ov, sizeof(ov));
			ov.hEvent = readEvent;
			ResetEvent(readEvent);
			ok = ReadFile(pipe, buffer, TRDP_READ_BUFFER, NULL, &ov);
			if (!ok && GetLastError() != ERROR_IO_PENDING)
			{
				EnterCriticalSection(&b->lock);
				if (b->pipe == pipe)
				{
					bridgeClosePipeLocked(b);
				}
				LeaveCriticalSection(&b->lock);
				WaitForSingleObject(b->stopEvent, TRDP_RETRY_MS);
				continue;
			}
			waits[0] = b->stopEvent;
			waits[1] = readEvent;
			w = WaitForMultipleObjects(2, waits, FALSE, INFINITE);
			if (w != WAIT_OBJECT_0 + 1)
			{
				/* Parada: se cancela la lectura y se espera a que termine. */
				EnterCriticalSection(&b->lock);
				if (b->pipe == pipe)
				{
					CancelIoEx(pipe, &ov);
				}
				LeaveCriticalSection(&b->lock);
				WaitForSingleObject(readEvent, 2000);
				break;
			}
			if (!GetOverlappedResult(pipe, &ov, &got, FALSE) || got == 0)
			{
				/* Tiresias se ha cerrado o ha soltado la conexión. */
				EnterCriticalSection(&b->lock);
				if (b->pipe == pipe)
				{
					bridgeClosePipeLocked(b);
				}
				LeaveCriticalSection(&b->lock);
				continue;
			}
			if (!b->closed && b->channel)
			{
				HRESULT hr = b->channel->lpVtbl->Write(b->channel, got, buffer, NULL);
				if (FAILED(hr))
				{
					trdpLog(L"TiresiasRdp: error 0x%08lx al escribir en el canal", (unsigned long)hr);
				}
			}
		}
	}
done:
	if (readEvent)
	{
		CloseHandle(readEvent);
	}
	if (buffer)
	{
		HeapFree(GetProcessHeap(), 0, buffer);
	}
	if (SUCCEEDED(hrCom))
	{
		CoUninitialize();
	}
	b->iface.lpVtbl->Release(&b->iface);
	return 0;
}

static HRESULT bridgeCreate(IWTSVirtualChannel *channel, TrdpBridge **out)
{
	TrdpBridge *b = (TrdpBridge *)HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, sizeof(TrdpBridge));
	if (!b)
	{
		return E_OUTOFMEMORY;
	}
	InterlockedIncrement(&g_objects);
	b->iface.lpVtbl = &g_bridgeVtbl;
	b->refs = 1;
	b->pipe = INVALID_HANDLE_VALUE;
	InitializeCriticalSection(&b->lock);
	b->channel = channel;
	channel->lpVtbl->AddRef(channel);
	b->writeEvent = CreateEventW(NULL, TRUE, FALSE, NULL);
	b->stopEvent = CreateEventW(NULL, TRUE, FALSE, NULL);
	if (!b->writeEvent || !b->stopEvent)
	{
		bridge_Release(&b->iface);
		return E_OUTOFMEMORY;
	}
	/* El hilo tiene su propia referencia. */
	bridge_AddRef(&b->iface);
	b->thread = CreateThread(NULL, 0, bridgeThread, b, 0, NULL);
	if (!b->thread)
	{
		bridge_Release(&b->iface);
		bridge_Release(&b->iface);
		return HRESULT_FROM_WIN32(GetLastError());
	}
	*out = b;
	return S_OK;
}

/* ================================================================ retrollamada del oyente */
typedef struct TrdpListenerCallback
{
	IWTSListenerCallback iface;
	volatile LONG refs;
} TrdpListenerCallback;

static HRESULT STDMETHODCALLTYPE listener_QueryInterface(IWTSListenerCallback *This, REFIID riid, void **ppv)
{
	if (!ppv)
	{
		return E_POINTER;
	}
	if (IsEqualIID(riid, &IID_IUnknown) || IsEqualIID(riid, &IID_IWTSListenerCallback))
	{
		*ppv = This;
		This->lpVtbl->AddRef(This);
		return S_OK;
	}
	*ppv = NULL;
	return E_NOINTERFACE;
}

static ULONG STDMETHODCALLTYPE listener_AddRef(IWTSListenerCallback *This)
{
	return (ULONG)InterlockedIncrement(&((TrdpListenerCallback *)This)->refs);
}

static ULONG STDMETHODCALLTYPE listener_Release(IWTSListenerCallback *This)
{
	TrdpListenerCallback *l = (TrdpListenerCallback *)This;
	LONG r = InterlockedDecrement(&l->refs);
	if (r == 0)
	{
		HeapFree(GetProcessHeap(), 0, l);
		InterlockedDecrement(&g_objects);
	}
	return (ULONG)r;
}

static HRESULT STDMETHODCALLTYPE listener_OnNewChannelConnection(IWTSListenerCallback *This, IWTSVirtualChannel *pChannel, BSTR data, BOOL *pbAccept, IWTSVirtualChannelCallback **ppCallback)
{
	TrdpBridge *b = NULL;
	HRESULT hr;
	(void)This;
	(void)data;
	if (!pbAccept || !ppCallback)
	{
		return E_POINTER;
	}
	*pbAccept = FALSE;
	*ppCallback = NULL;
	if (!pChannel)
	{
		return E_INVALIDARG;
	}
	hr = bridgeCreate(pChannel, &b);
	if (FAILED(hr))
	{
		return hr;
	}
	trdpLog(L"TiresiasRdp: canal abierto por el equipo remoto");
	*pbAccept = TRUE;
	*ppCallback = &b->iface; /* se transfiere la referencia inicial */
	return S_OK;
}

static IWTSListenerCallbackVtbl g_listenerVtbl = {
	listener_QueryInterface,
	listener_AddRef,
	listener_Release,
	listener_OnNewChannelConnection,
};

/* ================================================================ complemento */
typedef struct TrdpPlugin
{
	IWTSPlugin iface;
	volatile LONG refs;
	IWTSListener *listener;
} TrdpPlugin;

static HRESULT STDMETHODCALLTYPE plugin_QueryInterface(IWTSPlugin *This, REFIID riid, void **ppv)
{
	if (!ppv)
	{
		return E_POINTER;
	}
	if (IsEqualIID(riid, &IID_IUnknown) || IsEqualIID(riid, &IID_IWTSPlugin))
	{
		*ppv = This;
		This->lpVtbl->AddRef(This);
		return S_OK;
	}
	*ppv = NULL;
	return E_NOINTERFACE;
}

static ULONG STDMETHODCALLTYPE plugin_AddRef(IWTSPlugin *This)
{
	return (ULONG)InterlockedIncrement(&((TrdpPlugin *)This)->refs);
}

static ULONG STDMETHODCALLTYPE plugin_Release(IWTSPlugin *This)
{
	TrdpPlugin *p = (TrdpPlugin *)This;
	LONG r = InterlockedDecrement(&p->refs);
	if (r == 0)
	{
		if (p->listener)
		{
			p->listener->lpVtbl->Release(p->listener);
		}
		HeapFree(GetProcessHeap(), 0, p);
		InterlockedDecrement(&g_objects);
	}
	return (ULONG)r;
}

static HRESULT STDMETHODCALLTYPE plugin_Initialize(IWTSPlugin *This, IWTSVirtualChannelManager *pChannelMgr)
{
	TrdpPlugin *p = (TrdpPlugin *)This;
	TrdpListenerCallback *cb;
	HRESULT hr;
	if (!pChannelMgr)
	{
		return E_INVALIDARG;
	}
	cb = (TrdpListenerCallback *)HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, sizeof(TrdpListenerCallback));
	if (!cb)
	{
		return E_OUTOFMEMORY;
	}
	InterlockedIncrement(&g_objects);
	cb->iface.lpVtbl = &g_listenerVtbl;
	cb->refs = 1;
	hr = pChannelMgr->lpVtbl->CreateListener(pChannelMgr, TRDP_CHANNEL_NAME, 0, &cb->iface, &p->listener);
	/* El gestor guarda su propia referencia a la retrollamada. */
	listener_Release(&cb->iface);
	if (FAILED(hr))
	{
		trdpLog(L"TiresiasRdp: CreateListener falló (0x%08lx)", (unsigned long)hr);
	}
	return hr;
}

static HRESULT STDMETHODCALLTYPE plugin_Connected(IWTSPlugin *This)
{
	(void)This;
	return S_OK;
}

static HRESULT STDMETHODCALLTYPE plugin_Disconnected(IWTSPlugin *This, DWORD dwDisconnectCode)
{
	(void)This;
	(void)dwDisconnectCode;
	return S_OK;
}

static HRESULT STDMETHODCALLTYPE plugin_Terminated(IWTSPlugin *This)
{
	TrdpPlugin *p = (TrdpPlugin *)This;
	if (p->listener)
	{
		p->listener->lpVtbl->Release(p->listener);
		p->listener = NULL;
	}
	return S_OK;
}

static IWTSPluginVtbl g_pluginVtbl = {
	plugin_QueryInterface,
	plugin_AddRef,
	plugin_Release,
	plugin_Initialize,
	plugin_Connected,
	plugin_Disconnected,
	plugin_Terminated,
};

/* ================================================================ fábrica de clases */
static HRESULT STDMETHODCALLTYPE factory_QueryInterface(IClassFactory *This, REFIID riid, void **ppv)
{
	if (!ppv)
	{
		return E_POINTER;
	}
	if (IsEqualIID(riid, &IID_IUnknown) || IsEqualIID(riid, &IID_IClassFactory))
	{
		*ppv = This;
		return S_OK;
	}
	*ppv = NULL;
	return E_NOINTERFACE;
}

static ULONG STDMETHODCALLTYPE factory_AddRef(IClassFactory *This)
{
	(void)This;
	return 2;
}

static ULONG STDMETHODCALLTYPE factory_Release(IClassFactory *This)
{
	(void)This;
	return 1;
}

static HRESULT STDMETHODCALLTYPE factory_CreateInstance(IClassFactory *This, IUnknown *outer, REFIID riid, void **ppv)
{
	TrdpPlugin *p;
	HRESULT hr;
	(void)This;
	if (!ppv)
	{
		return E_POINTER;
	}
	*ppv = NULL;
	if (outer)
	{
		return CLASS_E_NOAGGREGATION;
	}
	p = (TrdpPlugin *)HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, sizeof(TrdpPlugin));
	if (!p)
	{
		return E_OUTOFMEMORY;
	}
	InterlockedIncrement(&g_objects);
	p->iface.lpVtbl = &g_pluginVtbl;
	p->refs = 1;
	hr = plugin_QueryInterface(&p->iface, riid, ppv);
	plugin_Release(&p->iface);
	return hr;
}

static HRESULT STDMETHODCALLTYPE factory_LockServer(IClassFactory *This, BOOL lock)
{
	(void)This;
	if (lock)
	{
		InterlockedIncrement(&g_locks);
	}
	else
	{
		InterlockedDecrement(&g_locks);
	}
	return S_OK;
}

static IClassFactoryVtbl g_factoryVtbl = {
	factory_QueryInterface,
	factory_AddRef,
	factory_Release,
	factory_CreateInstance,
	factory_LockServer,
};

static IClassFactory g_factory = {&g_factoryVtbl};

/* ================================================================ exportaciones */
STDAPI DllGetClassObject(REFCLSID rclsid, REFIID riid, LPVOID *ppv)
{
	if (!ppv)
	{
		return E_POINTER;
	}
	*ppv = NULL;
	if (!IsEqualCLSID(rclsid, &CLSID_TiresiasRdpPlugin))
	{
		return CLASS_E_CLASSNOTAVAILABLE;
	}
	return factory_QueryInterface(&g_factory, riid, ppv);
}

STDAPI DllCanUnloadNow(void)
{
	return (g_objects == 0 && g_locks == 0) ? S_OK : S_FALSE;
}

/* Versión del complemento (la consulta Tiresias para saber qué copia está registrada). */
DWORD WINAPI TiresiasRdp_GetVersion(void)
{
	return 1;
}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID reserved)
{
	(void)reserved;
	if (reason == DLL_PROCESS_ATTACH)
	{
		g_module = inst;
		DisableThreadLibraryCalls(inst);
	}
	return TRUE;
}
