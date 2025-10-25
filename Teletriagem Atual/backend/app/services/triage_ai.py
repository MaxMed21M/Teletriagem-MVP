"""
Helpers to build prompts and parse results for AI-powered triage (Teletriagem).
Assinaturas públicas:
- build_user_prompt(payload: TriageCreate) -> str
- parse_model_response(text: str) -> Dict[str, Any] | TriageAIStruct

Este módulo é **stateless** e não realiza I/O.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional, TypedDict, Tuple

# ============================================================
# Integração com schemas (com fallback seguro)
# ============================================================

try:
    # Esperado no projeto
    from ..schemas import TriageCreate, TriageAIStruct  # type: ignore
except Exception:
    # Fallback mínimo para não quebrar em desenvolvimento
    from pydantic import BaseModel

    class _Vitals(BaseModel):
        hr: Optional[int] = None  # heart rate
        sbp: Optional[int] = None
        dbp: Optional[int] = None
        temp: Optional[float] = None
        spo2: Optional[int] = None

    class TriageCreate(BaseModel):  # type: ignore
        complaint: str
        age: Optional[int] = None
        vitals: Optional[_Vitals] = None

    class TriageAIStruct(BaseModel):  # type: ignore
        priority: str  # "emergent" | "urgent" | "non-urgent"
        red_flags: List[str]
        probable_causes: List[str]
        recommended_actions: List[str]
        disposition: str  # "ER", "Clinic same day", "Home care + watch", etc.


# ============================================================
# Conhecimento base: guias por sintoma
# ============================================================

class SymptomGuide(TypedDict, total=False):
    title: str
    keywords: List[str]
    perguntas: List[str]
    red_flags: List[str]
    notes: str
    age_min: int
    age_max: int


SYMPTOM_GUIDES: List[SymptomGuide] = [
    {
        "title": "Dor torácica ou sensação de aperto no peito",
        "keywords": [
            "dor torac",
            "dor no peito",
            "aperto no peito",
            "pressao no peito",
            "pressão no peito",
            "queimação no peito",
        ],
        "perguntas": [
            "Início súbito?",
            "Irradia para braço, mandíbula ou dorso?",
            "Associada a esforço físico?",
            "Dispneia, sudorese fria, náuseas ou vômitos?",
            "Duração > 20 minutos?",
        ],
        "red_flags": [
            "Dor intensa/súbita com dispneia, síncope ou sudorese fria",
            "Dor associada a esforço e que não melhora em repouso",
            "Saturação < 92% ou FR > 30",
            "PA sistólica < 90 mmHg",
        ],
        "notes": "Considerar SCA, TEP, dissecção aórtica; avaliar fatores de risco cardiovascular.",
        "age_min": 18,
    },
    {
        "title": "Dispneia / Falta de ar",
        "keywords": [
            "falta de ar",
            "dispneia",
            "cansaço para respirar",
            "fôlego curto",
        ],
        "perguntas": [
            "Início súbito ou progressivo?",
            "Associada a febre, tosse, dor torácica, sibilos?",
            "Ortopneia ou dispneia paroxística noturna?",
            "Edema de membros inferiores?",
        ],
        "red_flags": [
            "Uso de musculatura acessória",
            "Saturação < 92%",
            "Alteração do nível de consciência",
            "Cianose, FR > 30 irpm",
        ],
        "notes": "Considerar asma, DPOC, IC, pneumonia, TEP.",
    },
    {
        "title": "Febre",
        "keywords": ["febre", "febril", "temperatura alta"],
        "perguntas": [
            "Valores e duração da febre?",
            "Sintomas associados (tosse, dor, disúria, diarreia)?",
            "Contato com doentes? Viagens recentes?",
            "Antitérmicos usados e resposta?",
        ],
        "red_flags": [
            "Letargia, rigidez de nuca",
            "Sinais de choque (hipotensão, extremidades frias)",
            "Imunossupressão",
            "Idoso frágil ou lactente < 3 meses com febre",
        ],
        "notes": "Investigar foco; orientar hidratação, sinais de alarme e reavaliação.",
    },
]


# ============================================================
# Utilidades
# ============================================================

def _norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()
@lru_cache(maxsize=128)
def _cached_guides(complaint_norm: str, age_key: int) -> Tuple[SymptomGuide, ...]:
    selected: List[SymptomGuide] = []
    for g in SYMPTOM_GUIDES:
        # idade
        if "age_min" in g and age_key >= 0 and age_key < int(g["age_min"]):
            continue
        if "age_max" in g and age_key >= 0 and age_key > int(g["age_max"]):
            continue
        # keywords
        kws = [k.lower() for k in g.get("keywords", [])]
        if any(kw in complaint_norm for kw in kws):
            selected.append(g)
    return tuple(selected)


def _select_guides(complaint: str, age: Optional[int]) -> List[SymptomGuide]:
    # PERFORMANCE: cache leve para evitar reprocessar guias a cada requisição.
    norm = _norm(complaint)
    age_key = age if age is not None else -1
    return list(_cached_guides(norm, age_key))


def _format_vitals(v: Optional[Any]) -> str:
    if not v:
        return "Não informados."
    # Suporta Pydantic model ou dict
    d = v.dict() if hasattr(v, "dict") else dict(v)
    parts = []
    if d.get("hr") is not None:
        parts.append(f"FC: {d['hr']} bpm")
    if d.get("sbp") is not None or d.get("dbp") is not None:
        parts.append(f"PA: {d.get('sbp', '?')}/{d.get('dbp', '?')} mmHg")
    if d.get("temp") is not None:
        parts.append(f"T: {d['temp']} °C")
    if d.get("spo2") is not None:
        parts.append(f"SpO₂: {d['spo2']}%")
    return ", ".join(parts) if parts else "Não informados."


# ============================================================
# Prompt builder (✅ assinatura única com payload)
# ============================================================

# PERFORMANCE: evita recriar a especificação JSON do prompt a cada chamada.
_PROMPT_SPEC = (
    "Responda de forma breve, clara e **ESTRUTURADA em JSON** com as chaves abaixo:\n"
    "{\n"
    '  "priority": "emergent|urgent|non-urgent",\n'
    '  "red_flags": [list de strings],\n'
    '  "probable_causes": [list de strings],\n'
    '  "recommended_actions": [list de strings],\n'
    '  "disposition": "ER|Clinic same day|Clinic routine|Home care + watch"\n'
    "}\n"
    "Só retorne o JSON, sem explicações adicionais."
)

def build_user_prompt(payload: TriageCreate) -> str:
    """
    Constrói o prompt do usuário a partir do TriageCreate completo.
    """
    complaint = payload.complaint.strip()
    age = payload.age
    vitals_str = _format_vitals(payload.vitals)

    guides = _select_guides(complaint, age)
    blocks: List[str] = []

    header = (
        "Contexto do paciente:\n"
        f"- Queixa principal: {complaint}\n"
        f"- Idade: {age if age is not None else 'não informada'}\n"
        f"- Sinais vitais: {vitals_str}\n"
    )
    blocks.append(header)

    if guides:
        for g in guides:
            g_title = g.get("title", "Guia por sintoma")
            perguntas = g.get("perguntas", [])
            red_flags = g.get("red_flags", [])
            notes = g.get("notes", "")

            b = [f"Guia sugerido: {g_title}"]
            if perguntas:
                b.append("Perguntas úteis:")
                for q in perguntas:
                    b.append(f"- {q}")
            if red_flags:
                b.append("Red flags a verificar:")
                for rf in red_flags:
                    b.append(f"- {rf}")
            if notes:
                b.append(f"Notas: {notes}")
            blocks.append("\n".join(b))

    blocks.append(_PROMPT_SPEC)

    return "\n\n".join(blocks)


# ============================================================
# Parser de resposta do modelo
# ============================================================

_JSON_BLOCK_RE = re.compile(
    r"(?:```json\s*(\{.*?\})\s*```)|(\{.*\})",
    re.DOTALL | re.IGNORECASE,
)


def _try_load_json(s: str) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(s)
        if isinstance(data, dict):
            return data
        return None
    except Exception:
        return None


def parse_model_response(text: str):
    """
    Aceita:
      - JSON puro;
      - JSON dentro de bloco ```json ... ```
      - Texto livre (fallback para estrutura mínima).

    Retorna TriageAIStruct (se disponível) ou dict equivalente.
    """
    text = (text or "").strip()

    # 1) Tentativa direta
    data = _try_load_json(text)
    if not data:
        # 2) Extrair bloco JSON
        m = _JSON_BLOCK_RE.search(text)
        if m:
            candidate = m.group(1) or m.group(2) or ""
            data = _try_load_json(candidate)

    if not data:
        # 3) Fallback: heurística simples a partir de texto livre
        lower = text.lower()
        red_flags: List[str] = []
        probable: List[str] = []
        actions: List[str] = []
        disposition = "Clinic routine"
        priority = "non-urgent"

        # heurísticas bem conservadoras
        if "ir ao pronto-socorro" in lower or "emergência" in lower or "procurar a emergência" in lower:
            disposition = "ER"
            priority = "emergent"
        if "sinais de choque" in lower or "hipotensão" in lower or "saturação <" in lower:
            priority = "emergent"
        if "sinais de alarme" in lower:
            red_flags.append("Sinais de alarme descritos pelo modelo")

        data = {
            "priority": priority,
            "red_flags": red_flags,
            "probable_causes": probable,
            "recommended_actions": actions,
            "disposition": disposition,
        }

    # Normalização de chaves
    def _as_list(x: Any) -> List[str]:
        if x is None:
            return []
        if isinstance(x, list):
            return [str(i) for i in x]
        return [str(x)]

    norm = {
        "priority": str(data.get("priority", "non-urgent")),
        "red_flags": _as_list(data.get("red_flags")),
        "probable_causes": _as_list(data.get("probable_causes")),
        "recommended_actions": _as_list(data.get("recommended_actions")),
        "disposition": str(data.get("disposition", "Clinic routine")),
    }

    # Tenta instanciar TriageAIStruct se existir
    try:
        if hasattr(TriageAIStruct, "model_validate"):
            return TriageAIStruct.model_validate(norm)  # pydantic v2
        return TriageAIStruct(**norm)  # pydantic v1
    except Exception:
        # Se o schema real for diferente, devolve o dict normalizado
        return norm
