"""Nuevo Outlook para Windows (``olk.exe``, WebView2).

Todo el correo es una página web: sin este módulo cada documento se abría en
modo exploración y las letras de los atajos de Outlook (N nuevo, R responder,
Supr, Control+Mayúsculas+...) se convertían en navegación rápida. Como en
Teams, Slack o WhatsApp, empieza en modo foco; Tiresias+Espacio pasa al modo
exploración (por ejemplo, para leer un mensaje con las flechas).
"""

from __future__ import annotations

from . import AppModule as BaseAppModule


class AppModule(BaseAppModule):
	disableBrowseModeByDefault = True
