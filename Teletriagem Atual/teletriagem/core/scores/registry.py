"""Score registry to compose deterministic risk layers."""

from __future__ import annotations

from typing import Callable, Dict, Mapping

from ...content import load_pack

ScoreFunc = Callable[[Mapping[str, object], object], Dict[str, float]]

_REGISTRY: Dict[str, ScoreFunc] = {}


def register(name: str) -> Callable[[ScoreFunc], ScoreFunc]:
    def decorator(func: ScoreFunc) -> ScoreFunc:
        _REGISTRY[name] = func
        return func

    return decorator


def run_scores(pack_id: str, entry: Mapping[str, object], context) -> Dict[str, float]:
    pack = load_pack(pack_id)
    requested = [score.get("name") for score in pack.get("scores", [])]
    results: Dict[str, float] = {}
    for score_name in requested:
        func = _REGISTRY.get(score_name)
        if not func:
            continue
        try:
            results.update(func(entry, context))
        except Exception:
            continue
    return results
