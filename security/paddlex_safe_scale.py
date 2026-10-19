"""Safe replacement for PaddleX text-detection NormalizeImage scale parsing.

PaddleX 3.7.0--3.7.2 used ``eval(scale)``. This parser accepts only finite
numeric literals and bounded +, -, *, / expressions. It deliberately has no
access to Python names, calls, attributes, indexing, or exponentiation.

This module is a downstream patch artifact, not a ChessStream runtime
dependency. See SECURITY.md for the affected PaddleX code and application steps.
"""
from __future__ import annotations

import ast
import math


_MAX_EXPRESSION_LENGTH = 128
_MAX_AST_NODES = 32
_MAX_AST_DEPTH = 12


def parse_scale_expression(scale: str) -> float:
    """Parse the arithmetic subset used by PaddleX model YAML configs."""
    if not isinstance(scale, str) or not scale or len(scale) > _MAX_EXPRESSION_LENGTH:
        raise ValueError("scale must be a short finite number or arithmetic expression")
    try:
        expression = ast.parse(scale, mode="eval").body
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise ValueError("scale must be a finite number or arithmetic expression") from exc

    stack = [(expression, 1)]
    count = 0
    while stack:
        node, depth = stack.pop()
        count += 1
        if count > _MAX_AST_NODES or depth > _MAX_AST_DEPTH:
            raise ValueError("scale expression is too complex")
        stack.extend((child, depth + 1) for child in ast.iter_child_nodes(node))

    def evaluate(node: ast.AST) -> int | float:
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.UnaryOp) and type(node.op) in (ast.UAdd, ast.USub):
            value = evaluate(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and type(node.op) in (ast.Add, ast.Sub, ast.Mult, ast.Div):
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            return left / right
        raise ValueError("scale must contain only numeric literals and +, -, *, /")

    try:
        value = float(evaluate(expression))
    except (ArithmeticError, OverflowError, RecursionError, ValueError) as exc:
        raise ValueError("scale must be a finite number or arithmetic expression") from exc
    if not math.isfinite(value):
        raise ValueError("scale must be finite")
    return value
