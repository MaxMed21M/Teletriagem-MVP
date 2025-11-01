"""Prompt builders and glossary utilities."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List, Sequence

from ..schemas.triage import TriageCreate

ROOT = Path(__file__).resolve().parents[2]
GLOSSARY_PATH = ROOT / "kb_docs" / "glossario_ceara.csv"


def load_glossary(path: Path = GLOSSARY_PATH) -> Dict[str, str]:
    """Load glossary terms mapping colloquial expressions to clinical language."""

    glossary: Dict[str, str] = {}
    if not path.exists():
        return glossary
    with path.open("r", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            popular = row.get("popular", "").strip().lower()
            clinical = row.get("termo_clinico", "").strip()
            if popular and clinical:
                glossary[popular] = clinical
    return glossary


GLOSSARY = load_glossary()


def apply_glossary(text: str) -> str:
    """Return text appended with glossary clarification when applicable."""

    lowered = text.lower()
    additions: List[str] = []
    for popular, clinical in GLOSSARY.items():
        if popular in lowered:
            additions.append(f"{popular} = {clinical}")
    if not additions:
        return text
    return f"{text}\n\nTermos normalizados: {', '.join(additions)}."


def symptom_guides() -> str:
    """Return static guidance text for different chief complaints."""

    return (
        "Guia de Sintomas:\n"
        "- Dor torácica: avaliar irradiação, dispneia, sudorese, fatores de risco cardiovasculares.\n"
        "- Dispneia: checar padrão respiratório, saturação, sinais de choque, asma/COPD.\n"
        "- AVE: FAST positivo, alteração súbita, glicemia, anticoagulantes.\n"
        "- Dor abdominal: localização, defesa, vômitos persistentes, gravidez.\n"
        "- Febre: duração, foco, imunosupressão, idade <3 meses.\n"
        "- Pediatria: hidratação, estado geral, recusa alimentar, convulsões.\n"
    )


def red_flags_text() -> str:
    return (
        "Red Flags:\n"
        "- Alteração do nível de consciência\n"
        "- Instabilidade hemodinâmica\n"
        "- Dor intensa súbita\n"
        "- Dificuldade respiratória grave\n"
        "- Sinais de sepse\n"
        "- Gestante com sangramento ou dor abdominal intensa\n"
        "- Lactente <3 meses com febre\n"
    )


def build_system_prompt() -> str:
    """Return the system prompt for the triage assistant."""

    return (
        "Você é um assistente clínico de teletriagem brasileiro.\n"
        "Siga protocolos de classificação de risco e SEMPRE responda apenas JSON válido.\n"
        "Adote postura conservadora, destaque sinais de alerta e nunca substitua avaliação médica presencial.\n"
        "Não produza texto fora do JSON nem comentários adicionais.\n"
    )


def build_context_sections(rag_chunks: Sequence[Dict[str, str]]) -> str:
    """Build a context string including RAG excerpts."""

    if not rag_chunks:
        return ""
    context_lines = ["Contexto de Referências:"]
    for chunk in rag_chunks:
        title = chunk.get("title", "Fonte")
        snippet = chunk.get("snippet", "")
        source = chunk.get("source", "")
        context_lines.append(f"- {title}: {snippet} ({source})")
    return "\n".join(context_lines)


def build_user_prompt(data: TriageCreate, rag_chunks: Sequence[Dict[str, str]]) -> str:
    """Compose the final user prompt combining structured data and guidance."""

    sections = [
        "Instruções:\nRetorne JSON no formato especificado sem texto extra.",
        symptom_guides(),
        red_flags_text(),
    ]
    context = build_context_sections(rag_chunks)
    if context:
        sections.append(context)
    sections.append("Glossário Cearense:")
    glossary_lines = [f"- {popular} => {clinical}" for popular, clinical in GLOSSARY.items()][:50]
    if glossary_lines:
        sections.append("\n".join(glossary_lines))
    patient_lines = [
        "Dados do Paciente:",
        f"- Idade: {data.age}",
        f"- Sexo: {data.sex}",
        f"- Queixa principal: {apply_glossary(data.chief_complaint)}",
        f"- Duração dos sintomas: {data.symptoms_duration}",
        f"- Comorbidades: {data.comorbidities or 'não informado'}",
        f"- Medicações: {data.medications or 'não informado'}",
        f"- Alergias: {data.allergies or 'não informado'}",
        f"- Notas adicionais: {data.notes or 'sem notas'}",
    ]
    if data.vitals:
        vitals = data.vitals
        patient_lines.extend(
            [
                f"- PA: {vitals.systolic_bp or 'NA'}/{vitals.diastolic_bp or 'NA'}",
                f"- FC: {vitals.heart_rate or 'NA'}",
                f"- FR: {vitals.respiratory_rate or 'NA'}",
                f"- Temp: {vitals.temperature_c or 'NA'}",
                f"- SpO2: {vitals.spo2 or 'NA'}",
            ]
        )
    sections.append("\n".join(patient_lines))
    sections.append(
        "Formato de Saída JSON obrigatório:\n"
        "{\n  \"priority\": \"emergent|urgent|non-urgent\",\n"
        "  \"red_flags\": [\"...\"],\n"
        "  \"probable_causes\": [\"...\"],\n"
        "  \"recommended_actions\": [\"...\"],\n"
        "  \"disposition\": \"ED|SameDay|Routine|HomeCare\",\n"
        "  \"soap\": {\n    \"subjective\": \"...\",\n    \"objective\": \"...\",\n    \"assessment\": \"...\",\n    \"plan\": \"...\"\n  },\n"
        "  \"icd10_suggestions\": [\"...\"],\n"
        "  \"risk_stratification\": {\n    \"score_name\": \"...\",\n    \"score\": 0,\n    \"class\": \"...\"\n  },\n"
        "  \"confidence\": 0.0,\n"
        "  \"warnings\": [\"...\"],\n"
        "  \"audit\": {\"model\": \"...\", \"provider\": \"...\", \"latency_ms\": 0}\n}"
    )
    return "\n\n".join(sections)
