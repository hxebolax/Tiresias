"""Conexión automática del acceso remoto con datos propios (1.0.7).

Antes solo se podía conectar al iniciar con un preajuste; ahora las opciones
y el cuadro Conectar permiten guardar modo, tipo, servidor, puerto y clave
para conectar al iniciar Tiresias sin crear un preajuste.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

if "tiresias_test" not in os.path.basename(paths.DATA_DIR or ""):
	# Nunca se toca la carpeta de datos real.
	_TMPDATA = tempfile.mkdtemp(prefix="tiresias_test_autoconexion_")
	paths.setDataDir(_TMPDATA)
	paths.ensureDataDirs()

from tiresias.remote.certs import CertificateManager  # noqa: E402
from tiresias.remote.store import AUTOCONNECT_DATA_NAME, KIND_HOST, KIND_RELAY, Preset, RemoteStore  # noqa: E402


def _folder(test: unittest.TestCase) -> str:
	folder = tempfile.mkdtemp(prefix="tiresias_auto_")
	test.addCleanup(shutil.rmtree, folder, True)
	return folder


class StoreTests(unittest.TestCase):
	def test_custom_data_roundtrip_with_encrypted_key(self) -> None:
		path = os.path.join(_folder(self), "remoto.json")
		st = RemoteStore(path)
		self.assertFalse(st.autoconnectCustom)
		self.assertIsNone(st.autoconnectData)
		st.setAutoconnect(data=Preset(name="x", mode="slave", kind=KIND_RELAY, host="nvdaremote.com", key="secreta"), custom=True)
		with open(path, encoding="utf-8") as f:
			raw = json.load(f)
		self.assertTrue(raw["autoconnectCustom"])
		self.assertNotIn("secreta", json.dumps(raw))
		self.assertNotIn("name", raw["autoconnectData"])
		st2 = RemoteStore(path)
		self.assertTrue(st2.autoconnectCustom)
		self.assertEqual(st2.autoconnect, "")
		d = st2.autoconnectData
		self.assertEqual((d.name, d.mode, d.kind, d.host, d.key), (AUTOCONNECT_DATA_NAME, "slave", KIND_RELAY, "nvdaremote.com", "secreta"))

	def test_off_and_preset_keep_data(self) -> None:
		path = os.path.join(_folder(self), "remoto.json")
		st = RemoteStore(path)
		st.savePreset(Preset(name="Casa", key="1"))
		st.setAutoconnect(data=Preset(name="x", kind=KIND_HOST, port=7000, key="k"), custom=True)
		st.setAutoconnect()
		self.assertFalse(st.autoconnectCustom)
		self.assertEqual(st.autoconnectData.port, 7000)
		st.setAutoconnect(name="Casa")
		self.assertEqual(st.autoconnect, "Casa")
		self.assertFalse(st.autoconnectCustom)
		# Elegir un preajuste con la propiedad antigua también quita los datos propios.
		st.setAutoconnect(data=st.autoconnectData, custom=True)
		st.autoconnect = "Casa"
		self.assertFalse(RemoteStore(path).autoconnectCustom)
		self.assertEqual(RemoteStore(path).autoconnect, "Casa")

	def test_old_file_without_new_fields(self) -> None:
		path = os.path.join(_folder(self), "remoto.json")
		with open(path, "w", encoding="utf-8") as f:
			json.dump({"presets": [], "autoconnect": ""}, f)
		st = RemoteStore(path)
		self.assertFalse(st.autoconnectCustom)
		self.assertIsNone(st.autoconnectData)

	def test_undecryptable_key_is_kept_on_disk(self) -> None:
		path = os.path.join(_folder(self), "remoto.json")
		with open(path, "w", encoding="utf-8") as f:
			json.dump({"autoconnectCustom": True, "autoconnectData": {"mode": "slave", "kind": "relay", "host": "h", "port": 6837, "key": "dpapi:QUJDRA=="}}, f)
		st = RemoteStore(path)
		self.assertTrue(st.autoconnectKeyUnavailable())
		st.addRecent("otro")  # cualquier guardado
		with open(path, encoding="utf-8") as f:
			self.assertEqual(json.load(f)["autoconnectData"]["key"], "dpapi:QUJDRA==")


class ClientTests(unittest.TestCase):
	def _client(self, store: RemoteStore):
		from tiresias.remote.client import RemoteClient

		return RemoteClient(store, CertificateManager(_folder(self)))

	def test_connects_with_custom_data(self) -> None:
		st = RemoteStore(os.path.join(_folder(self), "r.json"))
		st.savePreset(Preset(name="Casa", key="1"))
		st.autoconnect = "Casa"
		st.setAutoconnect(data=Preset(name="x", mode="slave", host="servidor.ejemplo:7000", key="clave"), custom=True)
		c = self._client(st)
		with mock.patch.object(c, "connect") as connect:
			c.performAutoconnect()
		connect.assert_called_once()
		info = connect.call_args.args[0]
		self.assertEqual((info.hostname, info.port, info.key, info.mode.value), ("servidor.ejemplo", 7000, "clave", "slave"))

	def test_host_kind_starts_local_server(self) -> None:
		st = RemoteStore(os.path.join(_folder(self), "r.json"))
		st.setAutoconnect(data=Preset(name="x", mode="slave", kind=KIND_HOST, port=7100, key="clave"), custom=True)
		c = self._client(st)
		with mock.patch.object(c, "connect") as connect:
			c.performAutoconnect()
		self.assertEqual(connect.call_args.kwargs.get("hostPort"), 7100)

	def test_without_key_warns_and_does_not_connect(self) -> None:
		from tiresias.remote import client as clientModule

		st = RemoteStore(os.path.join(_folder(self), "r.json"))
		st.setAutoconnect(data=Preset(name="x", host="h", key=""), custom=True)
		c = self._client(st)
		said: list[str] = []
		with mock.patch.object(clientModule, "_say", side_effect=lambda t, interrupt=False: said.append(t)), mock.patch.object(c, "connect") as connect:
			c.performAutoconnect()
		connect.assert_not_called()
		self.assertTrue(said and "falta la clave" in said[0], said)

	def test_off_does_nothing(self) -> None:
		st = RemoteStore(os.path.join(_folder(self), "r.json"))
		st.setAutoconnect(data=Preset(name="x", host="h", key="k"), custom=False)
		c = self._client(st)
		with mock.patch.object(c, "connect") as connect:
			c.performAutoconnect()
		connect.assert_not_called()


class PanelTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		import wx

		from tiresias import remote
		from tiresias.gui import remote_dialogs
		from tiresias.gui import settings as S

		cls.wx = wx
		cls.app = wx.App.Get() or wx.App(False)
		remote.registerDefaults()
		captured: dict = {}
		with mock.patch.object(S, "registerPanel", side_effect=lambda pid, title, klass: captured.setdefault("cls", klass)):
			remote_dialogs.registerSettingsPanel()
		cls.panelClass = captured["cls"]
		cls.remote_dialogs = remote_dialogs

	def _panel(self, store: RemoteStore):
		frame = self.wx.Frame(None)
		self.addCleanup(frame.Destroy)
		fake = types.SimpleNamespace(store=store)
		with mock.patch.object(self.remote_dialogs, "_client", return_value=fake):
			panel = self.panelClass(frame)
		return panel

	def test_choices_and_save_custom(self) -> None:
		st = RemoteStore(os.path.join(_folder(self), "r.json"))
		st.savePreset(Preset(name="Casa", key="1"))
		st.addRecent("nvdaremote.com")
		p = self._panel(st)
		labels = [p._autoChoice.GetString(i) for i in range(p._autoChoice.GetCount())]
		self.assertEqual(len(labels), 3)
		self.assertIn("Casa", labels[2])
		self.assertEqual(p._autoChoice.GetSelection(), 0)
		self.assertFalse(p._autoKey.IsEnabled())
		self.assertEqual(p._autoHost.GetValue(), "nvdaremote.com")
		p._autoChoice.SetSelection(1)
		p._updateAuto()
		self.assertTrue(p._autoKey.IsEnabled())
		self.assertTrue(p._autoHost.IsEnabled())
		self.assertFalse(p._autoPort.IsEnabled())
		# Sin clave no deja guardar.
		with mock.patch.object(self.remote_dialogs.message_dialog, "messageBox") as box:
			self.assertFalse(p.isValid())
		box.assert_called_once()
		p._autoKey.SetValue("mi clave")
		self.assertTrue(p.isValid())
		p.onSave()
		self.assertTrue(st.autoconnectCustom)
		self.assertEqual((st.autoconnectData.host, st.autoconnectData.key, st.autoconnectData.mode), ("nvdaremote.com", "mi clave", "slave"))

	def test_link_fills_fields(self) -> None:
		st = RemoteStore(os.path.join(_folder(self), "r.json"))
		p = self._panel(st)
		p._autoChoice.SetSelection(1)
		p._autoHost.SetValue("nvdaremote://nvdaremote.com:6837/?key=abc&mode=master")
		self.assertTrue(p.isValid())
		self.assertEqual(p._autoKey.GetValue(), "abc")
		self.assertEqual(p._autoHost.GetValue(), "nvdaremote.com")
		# El modo del enlace es el de quien lo usa, como en el cuadro Conectar.
		self.assertEqual(p._autoMode.GetSelection(), 0)

	def test_preset_and_off(self) -> None:
		st = RemoteStore(os.path.join(_folder(self), "r.json"))
		st.savePreset(Preset(name="Casa", key="1"))
		st.setAutoconnect(data=Preset(name="x", host="h", key="k"), custom=True)
		p = self._panel(st)
		self.assertEqual(p._autoChoice.GetSelection(), 1)
		self.assertEqual(p._autoKey.GetValue(), "k")
		p._autoChoice.SetSelection(2)
		p.onSave()
		self.assertEqual(st.autoconnect, "Casa")
		self.assertFalse(st.autoconnectCustom)
		p2 = self._panel(st)
		self.assertEqual(p2._autoChoice.GetSelection(), 2)
		p2.resetToFactory()
		p2.onSave()
		self.assertEqual(st.autoconnect, "")
		self.assertFalse(st.autoconnectCustom)
		self.assertEqual(st.autoconnectData.key, "k")


class ConnectDialogTests(unittest.TestCase):
	def test_checkbox_saves_autoconnect(self) -> None:
		import wx

		from tiresias.gui import remote_dialogs

		app = wx.App.Get() or wx.App(False)  # noqa: F841
		st = RemoteStore(os.path.join(_folder(self), "r.json"))
		fake = types.SimpleNamespace(store=st, isActive=False, connect=lambda *a, **k: True)
		with mock.patch.object(remote_dialogs, "_client", return_value=fake), mock.patch.object(remote_dialogs, "_onCore") as onCore:
			dlg = remote_dialogs.ConnectDialog()
			self.assertFalse(dlg.autoCheck.GetValue())
			dlg.hostCombo.SetValue("nvdaremote.com")
			dlg.keyText.SetValue("clave")
			dlg.autoCheck.SetValue(True)
			dlg.onOk(None)
		onCore.assert_called_once()
		self.assertTrue(st.autoconnectCustom)
		self.assertEqual((st.autoconnectData.host, st.autoconnectData.key), ("nvdaremote.com", "clave"))
		with mock.patch.object(remote_dialogs, "_client", return_value=fake), mock.patch.object(remote_dialogs, "_onCore"):
			dlg = remote_dialogs.ConnectDialog()
			self.assertTrue(dlg.autoCheck.GetValue())
			self.assertEqual(dlg.keyText.GetValue(), "clave")
			dlg.autoCheck.SetValue(False)
			dlg.onOk(None)
		self.assertFalse(st.autoconnectCustom)


if __name__ == "__main__":
	unittest.main()
