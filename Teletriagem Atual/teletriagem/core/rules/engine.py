"""Rule evaluation engine for deterministic triage overrides."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Tuple

from ...content import load_pack
from ..normalizer.text import normalize_text

__all__ = ["apply_rules", "RuleEvaluationError"]


@dataclass(frozen=True)
class RuleEvaluationError(Exception):
    message: str

    def __str__(self) -> str:  # pragma: no cover - dataclass default
        return self.message


_ALLOWED_NAMES = {
    "hr",
    "sbp",
    "dbp",
    "temp",
    "spo2",
    "rr",
    "gcs",
    "any_red_flag",
}


class _SafeEvaluator(ast.NodeVisitor):
    def __init__(self, variables: Dict[str, Any]):
        self.variables = variables

    def visit_Module(self, node: ast.Module) -> Any:  # pragma: no cover - ast invariant
        return self.visit(node.body[0])

    def visit_Expr(self, node: ast.Expr) -> Any:  # pragma: no cover - ast invariant
        return self.visit(node.value)

    def visit_BoolOp(self, node: ast.BoolOp) -> bool:
        values = [self.visit(value) for value in node.values]
        if isinstance(node.op, ast.And):
            result = True
            for value in values:
                result = result and bool(value)
                if not result:
                    break
            return result
        if isinstance(node.op, ast.Or):
            result = False
            for value in values:
                if bool(value):
                    result = True
                    break
            return result
        raise RuleEvaluationError(f"Unsupported boolean operator: {node.op!r}")

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        operand = self.visit(node.operand)
        if isinstance(node.op, ast.Not):
            return not bool(operand)
        raise RuleEvaluationError(f"Unsupported unary operator: {node.op!r}")

    def visit_Compare(self, node: ast.Compare) -> bool:
        left = self.visit(node.left)
        result = True
        for operator, comparator in zip(node.ops, node.comparators):
            right = self.visit(comparator)
            if left is None or right is None:
                comparison = False
            elif isinstance(operator, ast.Lt):
                comparison = left < right
            elif isinstance(operator, ast.Gt):
                comparison = left > right
            elif isinstance(operator, ast.LtE):
                comparison = left <= right
            elif isinstance(operator, ast.GtE):
                comparison = left >= right
            elif isinstance(operator, ast.Eq):
                comparison = left == right
            elif isinstance(operator, ast.NotEq):
                comparison = left != right
            else:
                raise RuleEvaluationError(f"Unsupported comparator: {operator!r}")
            result = result and comparison
            left = right
        return result

    def visit_Name(self, node: ast.Name) -> Any:
        if node.id not in _ALLOWED_NAMES:
            raise RuleEvaluationError(f"Variable '{node.id}' not allowed in rule")
        return self.variables.get(node.id)

    def visit_Constant(self, node: ast.Constant) -> Any:  # pragma: no cover - trivial
        return node.value

    def generic_visit(self, node: ast.AST) -> Any:  # pragma: no cover - defensive
        raise RuleEvaluationError(f"Unsupported syntax in rule: {ast.dump(node)}")


def _evaluate(expression: str, variables: Dict[str, Any]) -> bool:
    tree = ast.parse(expression, mode="eval")
    evaluator = _SafeEvaluator(variables)
    return bool(evaluator.visit(tree.body))


def _match_red_flags(chief_complaint: str, flags: Iterable[str]) -> Tuple[str, ...]:
    normalized = normalize_text(chief_complaint)
    hits = []
    for flag in flags:
        parts = [part for part in normalize_text(flag).split() if part]
        if parts and all(part in normalized for part in parts):
            hits.append(flag)
    return tuple(hits)


def apply_rules(pack_id: str, context) -> tuple[bool, Dict[str, Any]]:
    """Evaluate disposition overrides for the selected pack."""

    pack = load_pack(pack_id)
    rules = pack.get("rules", {})
    overrides = rules.get("disposition_overrides", []) or []
    if not overrides:
        return False, {}

    triggered_flags = _match_red_flags(context.chief_complaint, pack.get("red_flags", []))
    variables = {
        "hr": context.vitals.hr,
        "sbp": context.vitals.sbp,
        "dbp": context.vitals.dbp,
        "temp": context.vitals.temp,
        "spo2": context.vitals.spo2,
        "rr": context.vitals.rr,
        "gcs": context.vitals.gcs,
        "any_red_flag": bool(triggered_flags),
    }

    for override in overrides:
        condition = override.get("when")
        decision = override.get("then", {})
        if not condition or not decision:
            continue
        try:
            if _evaluate(condition, variables):
                return True, {
                    "priority": decision.get("priority"),
                    "disposition": decision.get("disposition"),
                    "red_flags_triggered": triggered_flags,
                    "rule": condition,
                }
        except RuleEvaluationError:
            continue
    return False, {"red_flags_triggered": triggered_flags}
