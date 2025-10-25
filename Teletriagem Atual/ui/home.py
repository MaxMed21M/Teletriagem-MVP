from __future__ import annotations

import json
from typing import Any, Dict, Tuple

import httpx
import streamlit as st

from api_client import create_triage, default_api_base, list_triages, request_ai_triage

st.set_page_config(page_title="Teletriagem", page_icon="🩺", layout="wide")
st.title("🩺 Teletriagem — MVP")
st.caption("Formulário único para triagens manuais e suporte da IA.")

if "api_base_url" not in st.session_state:
    st.session_state.api_base_url = default_api_base()
if "debug_mode" not in st.session_state:
    st.session_state.debug_mode = False
if "last_ai_response" not in st.session_state:
    st.session_state.last_ai_response = None
if "last_ai_status" not in st.session_state:
    st.session_state.last_ai_status = None
if "last_ai_error" not in st.session_state:
    st.session_state.last_ai_error = None
if "last_ai_payload" not in st.session_state:
    st.session_state.last_ai_payload = None

with st.sidebar:
    st.header("Configuração")
    base_url = st.text_input("API base URL", st.session_state.api_base_url).strip()
    if base_url:
        st.session_state.api_base_url = base_url.rstrip("/")
    st.session_state.debug_mode = st.checkbox("Modo DEBUG", value=st.session_state.debug_mode)
    st.markdown(
        """
        - API: `python run_all.py`
        - UI: `http://127.0.0.1:8501`
        - Testes: consulte `scripts/test_api.ps1`
        """
    )

API_BASE = st.session_state.api_base_url
DEBUG_MODE = st.session_state.debug_mode

DEFAULTS = {
    "patient_name": "Paciente Teste",
    "age": 35,
    "complaint": "Dor no peito há 30 minutos",
    "hr": 88,
    "sbp": 130,
    "dbp": 85,
    "temp": 36.7,
    "spo2": 97,
}


def _triage_fields(prefix: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    col_a, col_b = st.columns([3, 1])
    with col_a:
        patient_name = st.text_input(
            "Nome do paciente",
            key=f"{prefix}_patient_name",
            value=DEFAULTS["patient_name"],
        )
    with col_b:
        age = st.number_input(
            "Idade",
            min_value=0,
            max_value=120,
            value=DEFAULTS["age"],
            step=1,
            key=f"{prefix}_age",
        )
    complaint = st.text_area(
        "Queixa principal",
        value=DEFAULTS["complaint"],
        key=f"{prefix}_complaint",
        height=120,
    )
    st.markdown("#### Sinais vitais (opcional)")
    col1, col2, col3 = st.columns(3)
    with col1:
        hr = st.number_input(
            "FC (bpm)",
            min_value=0,
            max_value=240,
            value=DEFAULTS["hr"],
            key=f"{prefix}_hr",
        )
    with col2:
        sbp = st.number_input(
            "PAS (mmHg)",
            min_value=0,
            max_value=300,
            value=DEFAULTS["sbp"],
            key=f"{prefix}_sbp",
        )
        dbp = st.number_input(
            "PAD (mmHg)",
            min_value=0,
            max_value=200,
            value=DEFAULTS["dbp"],
            key=f"{prefix}_dbp",
        )
    with col3:
        temp = st.number_input(
            "Temp (°C)",
            min_value=30.0,
            max_value=43.0,
            value=DEFAULTS["temp"],
            key=f"{prefix}_temp",
        )
        spo2 = st.number_input(
            "SpO₂ (%)",
            min_value=50,
            max_value=100,
            value=DEFAULTS["spo2"],
            key=f"{prefix}_spo2",
        )
    vitals = {
        "hr": int(hr),
        "sbp": int(sbp),
        "dbp": int(dbp),
        "temp": float(temp),
        "spo2": int(spo2),
    }
    payload = {
        "patient_name": patient_name.strip(),
        "age": int(age),
        "complaint": complaint.strip(),
        "vitals": vitals,
    }
    debug = {"payload": payload}
    return payload, debug


def _validate_payload(payload: Dict[str, Any]) -> tuple[bool, str | None]:
    if len(payload["patient_name"]) < 2:
        return False, "Informe um nome válido."
    if payload["age"] < 0 or payload["age"] > 120:
        return False, "Idade fora do intervalo permitido (0-120)."
    if len(payload["complaint"]) < 5:
        return False, "Descreva a queixa com pelo menos 5 caracteres."
    return True, None


manual_tab, ai_tab, history_tab = st.tabs(["Triagem manual", "Triagem com IA", "Histórico"])

with manual_tab:
    st.subheader("Registrar triagem manual")
    with st.form("manual_form"):
        manual_payload, manual_debug = _triage_fields("manual")
        submitted = st.form_submit_button("Registrar triagem manual", type="primary")
    if submitted:
        valid, msg = _validate_payload(manual_payload)
        if not valid:
            st.error(msg or "Corrija os campos obrigatórios.")
        else:
            try:
                created = create_triage(API_BASE, manual_payload)
            except httpx.HTTPError as exc:
                st.error(f"Erro ao registrar triagem: {exc}")
            else:
                st.success(f"Triagem criada com ID {created.get('id')}.")
                if DEBUG_MODE:
                    st.json(manual_debug)

with ai_tab:
    st.subheader("Solicitar suporte da IA")
    with st.form("ai_form"):
        ai_payload, ai_debug = _triage_fields("ai")
        submitted_ai = st.form_submit_button("Gerar triagem com IA", type="primary")
    if submitted_ai:
        valid, msg = _validate_payload(ai_payload)
        if not valid:
            st.error(msg or "Corrija os campos obrigatórios.")
        else:
            with st.spinner("Consultando /api/triage/ai..."):
                try:
                    response = request_ai_triage(API_BASE, ai_payload)
                except httpx.HTTPError as exc:
                    st.session_state.last_ai_payload = ai_payload
                    st.session_state.last_ai_response = None
                    st.session_state.last_ai_status = None
                    st.session_state.last_ai_error = str(exc)
                else:
                    st.session_state.last_ai_payload = ai_payload
                    st.session_state.last_ai_status = response.status_code
                    try:
                        st.session_state.last_ai_response = response.json()
                        st.session_state.last_ai_error = None
                    except ValueError:
                        st.session_state.last_ai_response = None
                        st.session_state.last_ai_error = "Resposta não é JSON válido."
    if st.session_state.last_ai_error:
        st.error(st.session_state.last_ai_error)
    if st.session_state.last_ai_status is not None:
        st.info(f"Status da última requisição: {st.session_state.last_ai_status}")

    result = st.session_state.last_ai_response
    if result is not None:
        tabs = st.tabs(["Estruturado", "Texto do modelo", "JSON bruto"])
        parsed = result.get("parsed") if isinstance(result, dict) else None
        parse_error = result.get("parse_error") if isinstance(result, dict) else None

        with tabs[0]:
            if parsed:
                st.json(parsed)
            else:
                st.warning(parse_error or "Parser retornou dados vazios.")
        with tabs[1]:
            st.code(result.get("model_text", ""), language="markdown")
        with tabs[2]:
            st.json(result)

        with st.expander("DEBUG", expanded=DEBUG_MODE):
            st.json({
                "status": st.session_state.last_ai_status,
                "request_payload": st.session_state.last_ai_payload,
                "response": result,
            })
    elif st.session_state.last_ai_status is not None and st.session_state.last_ai_error is None:
        st.warning("Nenhum JSON retornado pelo backend.")

with history_tab:
    st.subheader("Histórico recente")
    try:
        rows = list_triages(API_BASE, limit=20)
    except httpx.HTTPError as exc:
        st.error(f"Erro ao consultar histórico: {exc}")
    else:
        if not rows:
            st.info("Nenhuma triagem cadastrada ainda.")
        else:
            st.dataframe(rows, use_container_width=True)
