from teletriagem.api.llm import prompts
from teletriagem.api.schemas.triage import TriageCreate, VitalSigns


def sample_triage() -> TriageCreate:
    return TriageCreate(
        age=45,
        sex="male",
        chief_complaint="dor no peito",
        symptoms_duration="2 horas",
        vitals=VitalSigns(systolic_bp=140, diastolic_bp=90, heart_rate=100),
    )


def test_prompt_contains_sections():
    prompt = prompts.build_user_prompt(sample_triage(), [])
    assert "Guia de Sintomas" in prompt
    assert "Red Flags" in prompt
    assert "Formato de Saída JSON" in prompt


def test_glossary_applied():
    text = prompts.apply_glossary("Paciente com catarro preso")
    assert "catarro preso" in text.lower()
    assert "Termos" in text
