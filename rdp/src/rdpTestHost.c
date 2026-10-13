/*
 * rdpTestHost.exe: programa de pruebas de tiresiasRdpClient.dll (no se
 * distribuye).
 *
 * Hace de cliente de Escritorio remoto con objetos COM falsos
 * (IWTSVirtualChannelManager, IWTSListener e IWTSVirtualChannel): carga la
 * biblioteca, crea el complemento, lo inicializa y, según las órdenes que
 * recibe por la entrada estándar (una por línea), simula el canal:
 *
 *   open           abre el canal «TiresiasRdp» (OnNewChannelConnection)
 *   send <texto>   el equipo remoto envía <texto> + "\n" (OnDataReceived)
 *   sleep <ms>     espera
 *   close          el canal se cierra (OnClose)
 *   quit           termina (Terminated, Release y DllCanUnloadNow)
 *
 * Por la salida estándar escribe lo que pasa, una línea por suceso:
 * LOADED, LISTEN <canal>, ACCEPT <0|1>, WRITE <datos>, CLOSED, UNLOAD <hr>.
 *
 * Uso: rdpTestHost.exe <ruta de tiresiasRdpClient.dll>
 */

#define WIN32_LEAN_AND_MEAN
#define CINTERFACE
#include <windows.h>
#include <objbase.h>
#include <tsvirtualchannels.h>
#include <stdio.h>
#include <string.h>

static const CLSID CLSID_TiresiasRdpPlugin = {0x8e634465, 0xd682, 0x43f3, {0x83, 0x42, 0x03, 0x81, 0xd3, 0xc8, 0x5b, 0x3e}};

static CRITICAL_SECTION g_out;
static IWTSListenerCallback *g_listenerCallback = NULL;

static void emit(const char *prefix, const char *data, size_t len)
{
	EnterCriticalSection(&g_out);
	fputs(prefix, stdout);
	if (data)
	{
		fputc(' ', stdout);
		fwrite(data, 1, len, stdout);
	}
	fputc('\n', stdout);
	fflush(stdout);
	LeaveCriticalSection(&g_out);
}

/* ------------------------------------------------------------ IUnknown genérico */
typedef struct FakeObj
{
	void *vtbl;
	volatile LONG refs;
	const IID *iid;
} FakeObj;

static HRESULT STDMETHODCALLTYPE fake_QueryInterface(void *This, REFIID riid, void **ppv)
{
	FakeObj *o = (FakeObj *)This;
	if (IsEqualIID(riid, &IID_IUnknown) || IsEqualIID(riid, o->iid))
	{
		*ppv = This;
		InterlockedIncrement(&o->refs);
		return S_OK;
	}
	*ppv = NULL;
	return E_NOINTERFACE;
}

static ULONG STDMETHODCALLTYPE fake_AddRef(void *This)
{
	return (ULONG)InterlockedIncrement(&((FakeObj *)This)->refs);
}

static ULONG STDMETHODCALLTYPE fake_Release(void *This)
{
	/* Los objetos falsos son estáticos: solo se cuentan las referencias. */
	return (ULONG)InterlockedDecrement(&((FakeObj *)This)->refs);
}

/* Envolturas con el tipo de cada interfaz (sin conversiones de punteros). */
#define FAKE_IUNKNOWN(T) 	static HRESULT STDMETHODCALLTYPE T##_QI(T *This, REFIID riid, void **ppv) { return fake_QueryInterface(This, riid, ppv); } 	static ULONG STDMETHODCALLTYPE T##_AddRef(T *This) { return fake_AddRef(This); } 	static ULONG STDMETHODCALLTYPE T##_Release(T *This) { return fake_Release(This); }

FAKE_IUNKNOWN(IWTSListener)
FAKE_IUNKNOWN(IWTSVirtualChannelManager)
FAKE_IUNKNOWN(IWTSVirtualChannel)

/* ------------------------------------------------------------ IWTSListener */
static HRESULT STDMETHODCALLTYPE listener_GetConfiguration(IWTSListener *This, IPropertyBag **ppPropertyBag)
{
	(void)This;
	if (ppPropertyBag)
	{
		*ppPropertyBag = NULL;
	}
	return E_NOTIMPL;
}

static IWTSListenerVtbl g_listenerVtbl = {
	IWTSListener_QI,
	IWTSListener_AddRef,
	IWTSListener_Release,
	listener_GetConfiguration,
};
static FakeObj g_listener = {&g_listenerVtbl, 1, &IID_IWTSListener};

/* ------------------------------------------------------------ IWTSVirtualChannelManager */
static HRESULT STDMETHODCALLTYPE mgr_CreateListener(IWTSVirtualChannelManager *This, const char *name, ULONG flags, IWTSListenerCallback *cb, IWTSListener **ppListener)
{
	(void)This;
	(void)flags;
	emit("LISTEN", name, strlen(name));
	if (!cb || !ppListener)
	{
		return E_POINTER;
	}
	cb->lpVtbl->AddRef(cb);
	g_listenerCallback = cb;
	fake_AddRef(&g_listener);
	*ppListener = (IWTSListener *)&g_listener;
	return S_OK;
}

static IWTSVirtualChannelManagerVtbl g_mgrVtbl = {
	IWTSVirtualChannelManager_QI,
	IWTSVirtualChannelManager_AddRef,
	IWTSVirtualChannelManager_Release,
	mgr_CreateListener,
};
static FakeObj g_mgr = {&g_mgrVtbl, 1, &IID_IWTSVirtualChannelManager};

/* ------------------------------------------------------------ IWTSVirtualChannel */
static HRESULT STDMETHODCALLTYPE channel_Write(IWTSVirtualChannel *This, ULONG cbSize, BYTE *pBuffer, IUnknown *reserved)
{
	ULONG start = 0;
	ULONG i;
	(void)This;
	(void)reserved;
	/* Una línea de salida por cada línea de datos. */
	for (i = 0; i < cbSize; i++)
	{
		if (pBuffer[i] == '\n')
		{
			emit("WRITE", (const char *)pBuffer + start, i - start);
			start = i + 1;
		}
	}
	if (start < cbSize)
	{
		emit("WRITE", (const char *)pBuffer + start, cbSize - start);
	}
	return S_OK;
}

static HRESULT STDMETHODCALLTYPE channel_Close(IWTSVirtualChannel *This)
{
	(void)This;
	return S_OK;
}

static IWTSVirtualChannelVtbl g_channelVtbl = {
	IWTSVirtualChannel_QI,
	IWTSVirtualChannel_AddRef,
	IWTSVirtualChannel_Release,
	channel_Write,
	channel_Close,
};
static FakeObj g_channel = {&g_channelVtbl, 1, &IID_IWTSVirtualChannel};

/* ------------------------------------------------------------ programa */
int wmain(int argc, wchar_t **argv)
{
	typedef HRESULT(STDAPICALLTYPE * GetClassObjectFn)(REFCLSID, REFIID, LPVOID *);
	typedef HRESULT(STDAPICALLTYPE * CanUnloadFn)(void);
	HMODULE dll;
	GetClassObjectFn getClassObject;
	CanUnloadFn canUnload;
	IClassFactory *factory = NULL;
	IUnknown *unk = NULL;
	IWTSPlugin *plugin = NULL;
	IWTSVirtualChannelCallback *channelCb = NULL;
	char line[65536];
	HRESULT hr;
	char msg[64];

	InitializeCriticalSection(&g_out);
	if (argc < 2)
	{
		fputs("Uso: rdpTestHost.exe <tiresiasRdpClient.dll>\n", stderr);
		return 2;
	}
	CoInitializeEx(NULL, COINIT_MULTITHREADED);
	dll = LoadLibraryW(argv[1]);
	if (!dll)
	{
		sprintf_s(msg, sizeof(msg), "%lu", GetLastError());
		emit("ERROR LoadLibrary", msg, strlen(msg));
		return 1;
	}
	getClassObject = (GetClassObjectFn)GetProcAddress(dll, "DllGetClassObject");
	canUnload = (CanUnloadFn)GetProcAddress(dll, "DllCanUnloadNow");
	if (!getClassObject || !canUnload)
	{
		emit("ERROR exportaciones", NULL, 0);
		return 1;
	}
	hr = getClassObject(&CLSID_TiresiasRdpPlugin, &IID_IClassFactory, (void **)&factory);
	if (FAILED(hr))
	{
		sprintf_s(msg, sizeof(msg), "0x%08lx", (unsigned long)hr);
		emit("ERROR DllGetClassObject", msg, strlen(msg));
		return 1;
	}
	hr = factory->lpVtbl->CreateInstance(factory, NULL, &IID_IUnknown, (void **)&unk);
	factory->lpVtbl->Release(factory);
	if (FAILED(hr))
	{
		sprintf_s(msg, sizeof(msg), "0x%08lx", (unsigned long)hr);
		emit("ERROR CreateInstance", msg, strlen(msg));
		return 1;
	}
	hr = unk->lpVtbl->QueryInterface(unk, &IID_IWTSPlugin, (void **)&plugin);
	unk->lpVtbl->Release(unk);
	if (FAILED(hr))
	{
		sprintf_s(msg, sizeof(msg), "0x%08lx", (unsigned long)hr);
		emit("ERROR QueryInterface", msg, strlen(msg));
		return 1;
	}
	emit("LOADED", NULL, 0);
	hr = plugin->lpVtbl->Initialize(plugin, (IWTSVirtualChannelManager *)&g_mgr);
	if (FAILED(hr) || !g_listenerCallback)
	{
		emit("ERROR Initialize", NULL, 0);
		return 1;
	}
	plugin->lpVtbl->Connected(plugin);

	while (fgets(line, sizeof(line), stdin))
	{
		size_t n = strlen(line);
		while (n && (line[n - 1] == '\n' || line[n - 1] == '\r'))
		{
			line[--n] = 0;
		}
		if (n >= 3 && (unsigned char)line[0] == 0xEF && (unsigned char)line[1] == 0xBB && (unsigned char)line[2] == 0xBF)
		{
			/* Marca de orden de bytes que añaden algunas consolas. */
			memmove(line, line + 3, n - 2);
			n -= 3;
		}
		if (strcmp(line, "open") == 0)
		{
			BOOL accept = FALSE;
			if (channelCb)
			{
				channelCb->lpVtbl->OnClose(channelCb);
				channelCb->lpVtbl->Release(channelCb);
				channelCb = NULL;
			}
			hr = g_listenerCallback->lpVtbl->OnNewChannelConnection(g_listenerCallback, (IWTSVirtualChannel *)&g_channel, NULL, &accept, &channelCb);
			emit(SUCCEEDED(hr) && accept && channelCb ? "ACCEPT 1" : "ACCEPT 0", NULL, 0);
		}
		else if (strncmp(line, "send ", 5) == 0)
		{
			if (channelCb)
			{
				line[n] = '\n';
				channelCb->lpVtbl->OnDataReceived(channelCb, (ULONG)(n - 5 + 1), (BYTE *)line + 5);
				emit("SENT", NULL, 0);
			}
		}
		else if (strncmp(line, "sleep ", 6) == 0)
		{
			Sleep((DWORD)atoi(line + 6));
		}
		else if (strcmp(line, "close") == 0)
		{
			if (channelCb)
			{
				channelCb->lpVtbl->OnClose(channelCb);
				channelCb->lpVtbl->Release(channelCb);
				channelCb = NULL;
			}
			emit("CLOSED", NULL, 0);
		}
		else if (strcmp(line, "quit") == 0)
		{
			break;
		}
	}
	if (channelCb)
	{
		channelCb->lpVtbl->OnClose(channelCb);
		channelCb->lpVtbl->Release(channelCb);
		channelCb = NULL;
	}
	plugin->lpVtbl->Disconnected(plugin, 0);
	plugin->lpVtbl->Terminated(plugin);
	plugin->lpVtbl->Release(plugin);
	g_listenerCallback->lpVtbl->Release(g_listenerCallback);
	g_listenerCallback = NULL;
	/* El hilo del puente suelta su referencia al terminar. */
	{
		int i;
		for (i = 0; i < 50 && canUnload() != S_OK; i++)
		{
			Sleep(20);
		}
	}
	hr = canUnload();
	sprintf_s(msg, sizeof(msg), "%s", hr == S_OK ? "S_OK" : "S_FALSE");
	emit("UNLOAD", msg, strlen(msg));
	sprintf_s(msg, sizeof(msg), "channel=%ld listener=%ld", g_channel.refs, g_listener.refs);
	emit("REFS", msg, strlen(msg));
	FreeLibrary(dll);
	CoUninitialize();
	return 0;
}
