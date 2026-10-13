"""Servicios de traducción (cada archivo es un plugin que hereda de ``TraductorBase``)."""

from ..nucleo.gestor_traductores import InfoTraductor, TraductorBase

__all__ = ["TraductorBase", "InfoTraductor"]
