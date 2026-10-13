"""Calculadora Express: resuelve las operaciones aritméticas que aparecen en el texto.

Sin ``eval``: se analiza el árbol sintáctico y solo se admiten números,
suma, resta, multiplicación, división, potencia y signo, con límites de
complejidad, tamaño de los números y exponente.
"""

from __future__ import annotations

import ast
import operator
import re

from . import HerramientaBase, MetadatosHerramienta

PATRON = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?\s*[-+*/^x×÷]\s*\d+(?:[.,]\d+)?(?:\s*[-+*/^x×÷]\s*\d+(?:[.,]\d+)?)*(?![\w.])")
#: Fechas (2026-10-08, 08/10/2026) que no son operaciones.
FECHA = re.compile(r"^(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})$")
OPERADORES = {
	ast.Add: operator.add,
	ast.Sub: operator.sub,
	ast.Mult: operator.mul,
	ast.Div: operator.truediv,
	ast.Pow: operator.pow,
	ast.UAdd: operator.pos,
	ast.USub: operator.neg,
}


def evaluar(expresion: str):
	arbol = ast.parse(expresion, mode="eval")
	if sum(1 for _n in ast.walk(arbol)) > 40:
		raise ValueError("expresión demasiado compleja")

	def calcular(nodo):
		if isinstance(nodo, ast.Expression):
			return calcular(nodo.body)
		if isinstance(nodo, ast.Constant) and type(nodo.value) in (int, float):
			if abs(nodo.value) > 1e100:
				raise ValueError("número demasiado grande")
			return nodo.value
		if isinstance(nodo, ast.UnaryOp) and type(nodo.op) in OPERADORES:
			return OPERADORES[type(nodo.op)](calcular(nodo.operand))
		if isinstance(nodo, ast.BinOp) and type(nodo.op) in OPERADORES:
			izquierda = calcular(nodo.left)
			derecha = calcular(nodo.right)
			if isinstance(nodo.op, ast.Pow) and abs(derecha) > 1000:
				raise ValueError("exponente demasiado grande")
			resultado = OPERADORES[type(nodo.op)](izquierda, derecha)
			if isinstance(resultado, complex) or abs(resultado) > 1e100:
				raise ValueError("resultado demasiado grande")
			return resultado
		raise ValueError("operación no permitida")

	return calcular(arbol)


def formatear_numero(valor) -> str:
	if isinstance(valor, float):
		if valor.is_integer() and abs(valor) < 1e15:
			return str(int(valor))
		return "{:.10g}".format(valor)
	return str(valor)


def resolver_operaciones(texto: str) -> list[str]:
	resultados = []
	vistos: set[str] = set()
	for operacion in PATRON.findall(texto or ""):
		if operacion in vistos or FECHA.match(operacion.replace(" ", "")):
			continue
		vistos.add(operacion)
		expresion = operacion.replace("^", "**").replace("×", "*").replace("x", "*").replace("÷", "/").replace(",", ".")
		try:
			resultados.append("{} = {}".format(operacion, formatear_numero(evaluar(expresion))))
		except (ValueError, SyntaxError, ZeroDivisionError, OverflowError, TypeError):
			continue
	return resultados


class HerramientaCalculadora(HerramientaBase):
	METADATOS = MetadatosHerramienta(
		nombre="Calculadora Express",
		version="1.0.0",
		descripcion="Busca y resuelve operaciones matemáticas básicas en el texto",
		autor="Héctor J. Benítez Corredera",
		categoria="utilidades",
	)

	def ejecutar(self, **kwargs):
		return resolver_operaciones(self.texto_de(kwargs))
