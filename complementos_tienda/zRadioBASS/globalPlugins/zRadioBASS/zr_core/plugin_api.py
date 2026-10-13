# -*- coding: utf-8 -*-
# Copyright (C) 2025-2026 Héctor J. Benítez Corredera <xebolax@gmail.com>
# Este archivo está cubierto por la Licencia Pública General GNU.

"""Módulo ``zradiobass``: lo que pueden importar los plugins.

Ejemplo: ``from zradiobass import PluginBase, EventType, Station, log``.
"""

from __future__ import annotations

from tiresias.log import getLogger

from .events import Event, EventBus, EventType
from .models import Category, Favorite, PlaybackHistory, ScheduledRecording, SearchFilters, Station
from .player import PlayerState, format_duration
from .plugin_manager import PluginBase, PluginMetadata, PluginState

#: Registrador para los plugins (``log.info(...)`` va al registro de Tiresias).
log = getLogger("zRadioBASS.plugin")

__all__ = [
	"PluginBase",
	"PluginMetadata",
	"PluginState",
	"EventType",
	"Event",
	"EventBus",
	"Station",
	"Favorite",
	"Category",
	"PlaybackHistory",
	"ScheduledRecording",
	"SearchFilters",
	"PlayerState",
	"format_duration",
	"log",
]
