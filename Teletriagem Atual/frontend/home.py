"""Streamlit UI for the Teletriagem project (MVP com UX refinada)."""
from __future__ import annotations

import datetime as dt
import time
from typing import Any, Dict

import streamlit as st

from api_client import create_triage, list_triages, request_ai_triage

# ==============================
# Configurações iniciais
# ==============================
st.set_page_config(page_title="Teletriagem — MVP", page_icon="🩺", layout="wide")
st.title("🩺 Teletriagem — MVP")
st.caption("Registre triagens manuais ou peça apoio da IA com o mesmo formulário.")

# ==============================
# Estado da sessão
# ==============================
if "last_ai_response" not in st.session_state:
    st.session_state.last_ai_response = None

if "defaults" not in st.session_state:
    st.session_state.defaults = {
        "patient_name": "Paciente Teste",
        "age": 35,
        "complaint": "Febre alta, mialgia e cefaleia há 2 dias",
        # Defaults de vitais para acelerar testes
        "hr": 92,          # FC
        "sbp": 118,        # PAS
        "temp": 38.2,      # Temp
    }

# ==============================
# Helpers UI
# ==============================
def json_valid_badge(parsed: bool):
    """Renderiza um badge visual para indicar se o JSON veio válido (parsed=True) ou ambíguo."""
    color = "#16a34a" if parsed else "#f59e0b"
    label = "JSON válido ✅" if parsed else "JSON inválido/ambíguo ⚠️"
    st.markdown(
        f"""
        <div style="display:inline-block;padding:4px 8px;border-radius:8px;background:{color};color:white;font-weight:600;">
            {label}
        </div>
        """,
        unsafe_allow_html=True,
    )

def metric_row(latency_ms: int | None, model: str | None, session_id: int | None):
    cols = st.columns(3)
    cols[0].metric("Latência (ms)", value=latency_ms if latency_ms is not None else "-")
    cols[1].metric("Modelo", value=model or "-")
    cols[2].metric("Sessão", value=session_id if session_id is not None else "—")

def rerun_app() -> None:
    if hasattr(st, "experimental_rerun"):
        st.experimental_rerun()
    else:  # pragma: no cover - compat com versões recentes do Streamlit
        st.rerun()

@st.cache_data(ttl=30, show_spinner=False)
def fetch_sessions(limit: int, source: str | None) -> list[Dict[str, Any]]:
    return list_triages(limit=limit, source=source)

def _build_payload(prefix: str) -> Dict[str, Any]:
    """Constrói payload a partir de widgets, com defaults do session_state."""
    def widget_key(name: str) -> str:
        return f"{prefix}_{name}"

    col_name, col_age = st.columns([3, 1])
    with col_name:
        patient_name = st.text_input(
            "Nome do paciente",
            key=widget_key("patient_name"),
            value=st.session_state.defaults["patient_name"],
        )
    with col_age:
        age = st.number_input(
            "Idade",
            min_value=0,
            max_value=120,
            value=st.session_state.defaults["age"],
            key=widget_key("age"),
            step=1,
        )

    complaint = st.text_area(
        "Queixa principal",
        key=widget_key("complaint"),
        value=st.session_state.defaults["complaint"],
        height=120,
    )

    st.markdown("#### Sinais vitais (opcional)")
    col1, col2, col3 = st.columns(3)
    with col1:
        hr = st.number_input(
            "FC (bpm)",
            min_value=0,
            max_value=250,
            value=st.session_state.defaults["hr"],
            key=widget_key("hr"),
        )
    with col2:
        sbp = st.number_input(
            "PAS (mmHg)",
            min_value=0,
            max_value=300,
            value=st.session_state.defaults["sbp"],
            key=widget_key("sbp"),
        )
    with col3:
        temp = st.number_input(
            "Temp (°C)",
            min_value=30.0,
            max_value=43.0,
            value=st.session_state.defaults["temp"],
            key=widget_key("temp"),
        )

    vitals = {"hr": int(hr), "sbp": int(sbp), "temp": float(temp)}

    return {
        "patient_name": patient_name.strip(),
        "age": int(age),
        "complaint": complaint.strip(),
        "vitals": vitals,
    }

def _validate_minimal(payload: Dict[str, Any]) -> tuple[bool, str | None]:
    """Validações leves de UX antes de enviar ao backend."""
    if not payload["patient_name"] or len(payload["patient_name"]) < 2:
        return False, "Preencha um nome de paciente válido (mín. 2 caracteres)."
    if payload["age"] < 0 or payload["age"] > 120:
        return False, "Idade inválida (0–120)."
    if not payload["complaint"] or len(payload["complaint"]) < 5:
        return False, "Queixa muito curta (mín. 5 caracteres)."
    return True, None

# ==============================
# Abas
# ==============================
manual_tab, ai_tab, history_tab = st.tabs([
    "Triagem manual",
    "Triagem com IA",
    "Histórico",
])

# ==============================
# Triagem manual
# ==============================
with manual_tab:
    st.subheader("Registrar triagem manual")
    payload = _build_payload("manual")

    if st.button("Registrar triagem manual", type="primary"):
        ok, err = _validate_minimal(payload)
        if not ok:
            st.error(err or "Preencha os campos obrigatórios.")
        else:
            with st.spinner("Enviando triagem..."):
                try:
                    created = create_triage(payload)
                except Exception as exc:
                    st.error(f"Erro ao enviar triagem: {exc}")
                else:
                    st.success(f"Triagem #{created['id']} registrada com sucesso.")
                    # Atualiza defaults para agilizar próximo registro
                    st.session_state.defaults["patient_name"] = payload["patient_name"]
                    st.session_state.defaults["age"] = payload["age"]
                    st.session_state.defaults["complaint"] = payload["complaint"]
                    st.session_state.defaults["hr"] = payload["vitals"]["hr"]
                    st.session_state.defaults["sbp"] = payload["vitals"]["sbp"]
                    st.session_state.defaults["temp"] = payload["vitals"]["temp"]
                    st.session_state.last_ai_response = None

# ==============================
# Triagem com IA
# ==============================
with ai_tab:
    st.subheader("Gerar triagem assistida por IA")
    payload_ai = _build_payload("ai")

    if st.button("Solicitar apoio da IA", type="primary", key="ai_button"):
        ok, err = _validate_minimal(payload_ai)
        if not ok:
            st.error(err or "Preencha os campos obrigatórios.")
        else:
            with st.spinner("Chamando modelo no servidor Ollama..."):
                try:
                    t0 = time.perf_counter()
                    response = request_ai_triage(payload_ai)
                    elapsed_ms_fallback = int((time.perf_counter() - t0) * 1000)
                except Exception as exc:
                    st.error(f"Falha ao chamar a IA: {exc}")
                else:
                    st.session_state.last_ai_response = response
                    # Atualiza defaults
                    st.session_state.defaults["patient_name"] = payload_ai["patient_name"]
                    st.session_state.defaults["age"] = payload_ai["age"]
                    st.session_state.defaults["complaint"] = payload_ai["complaint"]
                    st.session_state.defaults["hr"] = payload_ai["vitals"]["hr"]
                    st.session_state.defaults["sbp"] = payload_ai["vitals"]["sbp"]
                    st.session_state.defaults["temp"] = payload_ai["vitals"]["temp"]
                    st.success("Resposta da IA recebida!")

    last_response = st.session_state.last_ai_response
    if last_response:
        st.markdown("#### Resultado da IA")
        # Badge de validade do JSON
        json_valid_badge(bool(last_response.get("parsed", False)))

        # Métricas
        metric_row(
            latency_ms=last_response.get("latency_ms"),
            model=last_response.get("model"),
            session_id=last_response.get("session_id"),
        )

        # Estrutura interpretada (quando disponível)
        if last_response.get("structured"):
            with st.expander("Estrutura (JSON validado)", expanded=True):
                st.json(last_response["structured"])
        else:
            st.info("Sem estrutura validada. Veja o texto bruto abaixo.")

        # Texto bruto (sempre exibido)
        with st.expander("Resposta bruta do modelo", expanded=False):
            st.code(last_response.get("raw", ""), language="markdown")

# ==============================
# Histórico
# ==============================
with history_tab:
    st.subheader("Histórico de triagens")
    col_filters = st.columns([1, 1, 1])
    source_filter = col_filters[0].selectbox(
        "Origem",
        options=["todas", "manual", "ai"],
        format_func=lambda v: "Todas" if v == "todas" else v.upper(),
    )
    limit = col_filters[1].slider("Limite", min_value=10, max_value=100, value=50, step=10)
    refresh = col_filters[2].button("Atualizar", type="secondary")

    if refresh:
        fetch_sessions.clear()
        rerun_app()

    source_param = None if source_filter == "todas" else source_filter

    try:
        sessions = fetch_sessions(limit, source_param)
    except Exception as exc:
        st.error(f"Erro ao carregar histórico: {exc}")
        sessions = []

    if not sessions:
        st.info("Nenhuma triagem encontrada.")
    else:
        for item in sessions:
            created_at = item.get("created_at")
            if isinstance(created_at, str):
                try:
                    created_dt = dt.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                except ValueError:
                    created_dt = created_at
            else:
                created_dt = created_at

            caption = (
                created_dt.strftime("%d/%m/%Y %H:%M")
                if isinstance(created_dt, dt.datetime)
                else created_at
            )
            title = f"#{item['id']} — {item['patient_name']} ({item['age']} anos)"
            with st.expander(title):
                st.caption(f"Registrado em: {caption} — Origem: {item.get('source', 'manual').upper()}")
                st.write(f"**Queixa:** {item.get('complaint')}")
                st.markdown("**Sinais vitais**")
                st.json(item.get("vitals") or {})

                if item.get("ai_struct"):
                    st.markdown("**Resumo da IA**")
                    st.json(item["ai_struct"])

                if item.get("ai_raw_text") and not item.get("ai_struct"):
                    st.markdown("**Saída bruta da IA**")
                    st.code(item["ai_raw_text"], language="markdown")

                if item.get("model_name"):
                    st.caption(
                        f"Modelo: {item['model_name']} — latência: {item.get('latency_ms', 'n/d')} ms"
                    )