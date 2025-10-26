from __future__ import annotations

import difflib
import json
from typing import Any, Dict, List

import httpx
import streamlit as st

from api_client import default_api_base, healthz, perform_triage, send_feedback

st.set_page_config(page_title="Teletriagem Resolutiva", page_icon="🩺", layout="wide")
st.title("🩺 Teletriagem Resolutiva — MVP 2025")

if "api_base_url" not in st.session_state:
    st.session_state.api_base_url = default_api_base()
if "triage_history" not in st.session_state:
    st.session_state.triage_history: List[Dict[str, Any]] = []
if "base_payload" not in st.session_state:
    st.session_state.base_payload: Dict[str, Any] | None = None
if "accumulated_context" not in st.session_state:
    st.session_state.accumulated_context: str = ""
if "last_response_json" not in st.session_state:
    st.session_state.last_response_json: str | None = None
if "last_result" not in st.session_state:
    st.session_state.last_result: Dict[str, Any] | None = None

with st.sidebar:
    st.header("Configuração")
    base_url = st.text_input("API base URL", st.session_state.api_base_url).strip()
    if base_url:
        st.session_state.api_base_url = base_url
    try:
        health = healthz(st.session_state.api_base_url)
    except httpx.HTTPError as exc:
        st.error(f"Falha ao consultar /healthz: {exc}")
        health = None
    if health:
        st.markdown(
            f"**Modelo:** `{health.get('model')}`\\n"
            f"**Prompt:** `{health.get('prompt_version')}`\\n"
            f"**Latência média:** {health.get('average_latency_ms')} ms\\n"
            f"**% JSON válido:** {health.get('valid_json_rate')}%"
        )
    st.divider()
    st.caption(
        """
        Fluxo recomendado:\n
        1. Preencha dados clínicos principais;\n
        2. Envie para a IA;\n
        3. Acrescente informações adicionais e refine;\n
        4. Envie feedback após revisar.
        """
    )

API_BASE = st.session_state.api_base_url


def _vitals_payload(hr: int | None, rr: int | None, sbp: int | None, dbp: int | None, temp: float | None, spo2: int | None) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    if hr is not None:
        data["heart_rate"] = int(hr)
    if rr is not None:
        data["respiratory_rate"] = int(rr)
    if sbp is not None:
        data["systolic_bp"] = int(sbp)
    if dbp is not None:
        data["diastolic_bp"] = int(dbp)
    if temp is not None:
        data["temperature"] = float(temp)
    if spo2 is not None:
        data["spo2"] = int(spo2)
    return data


st.subheader("Dados do paciente")
with st.form("triage_form"):
    col_a, col_b, col_c = st.columns([2, 1, 1])
    with col_a:
        patient_name = st.text_input("Nome (opcional)")
    with col_b:
        age = st.number_input("Idade", min_value=0, max_value=120, value=35)
    with col_c:
        sex_label = st.selectbox("Sexo", ["unknown", "female", "male", "other"], index=0)

    complaint = st.text_area("Queixa principal", height=120, value="Dor torácica súbita com dispneia")
    history = st.text_area("História breve", height=100, value="Início há 30 minutos durante esforço.")
    medications = st.text_area("Medicamentos em uso", height=60, value="AAS 100 mg/dia")
    allergies = st.text_area("Alergias", height=60, value="Nega alergias conhecidas")

    st.markdown("#### Sinais vitais")
    col1, col2, col3 = st.columns(3)
    with col1:
        hr = st.number_input("FC (bpm)", min_value=0, max_value=240, value=110)
        rr = st.number_input("FR (irpm)", min_value=0, max_value=60, value=24)
    with col2:
        sbp = st.number_input("PAS (mmHg)", min_value=0, max_value=300, value=95)
        dbp = st.number_input("PAD (mmHg)", min_value=0, max_value=200, value=60)
    with col3:
        temp = st.number_input("Temp (°C)", min_value=30.0, max_value=43.0, value=36.8)
        spo2 = st.number_input("SpO₂ (%)", min_value=50, max_value=100, value=89)

    additional_context = st.text_area("Observações adicionais", height=80, placeholder="Ex.: resultado de exames, antecedentes relevantes")

    submitted = st.form_submit_button("Gerar triagem", type="primary")

if submitted:
    payload: Dict[str, Any] = {
        "patient_name": patient_name.strip() or None,
        "age": int(age),
        "sex": sex_label,
        "complaint": complaint.strip(),
        "history": history.strip() or None,
        "medications": medications.strip() or None,
        "allergies": allergies.strip() or None,
        "vitals": _vitals_payload(hr, rr, sbp, dbp, temp, spo2),
        "additional_context": additional_context.strip() or None,
    }
    st.session_state.base_payload = payload
    st.session_state.accumulated_context = additional_context.strip() or ""
    try:
        result = perform_triage(API_BASE, payload)
    except httpx.HTTPError as exc:
        st.error(f"Falha ao gerar triagem: {exc}")
    else:
        st.session_state.last_result = result
        response_json = json.dumps(result.get("response", {}), ensure_ascii=False, indent=2)
        st.session_state.triage_history.append(result)
        st.session_state.last_response_json = response_json
        st.success("Triagem gerada com sucesso!")

result = st.session_state.last_result
if result:
    triage_id = result.get("triage_id")
    st.markdown(f"### Resultado atual — ID `{triage_id}`")

    col_info, col_actions = st.columns([2, 1])
    with col_info:
        response = result.get("response", {})
        st.metric("Prioridade", response.get("priority"))
        risk = response.get("risk_score", {})
        st.metric("Risco", f"{risk.get('value')} ({risk.get('scale')})", risk.get("rationale"))
        st.metric("Destino sugerido", response.get("disposition"))
        if result.get("guardrails_triggered"):
            st.warning("Guardrails aplicados: " + "; ".join(result["guardrails_triggered"]))
    with col_actions:
        pretty = json.dumps(result, ensure_ascii=False, indent=2)
        st.download_button(
            label="⬇️ Baixar JSON",
            data=pretty.encode("utf-8"),
            file_name=f"triage_{triage_id}.json",
            mime="application/json",
        )
        st.caption("Download inclui contexto, resposta e metadados.")

    tabs = st.tabs(["Resumo", "Detalhes", "RAG", "Resposta bruta"])
    with tabs[0]:
        st.subheader("Ações recomendadas")
        for action in response.get("recommended_actions", []):
            st.write(f"- {action}")
        st.subheader("Sinais de alerta")
        if response.get("red_flags"):
            for flag in response.get("red_flags", []):
                st.write(f"- {flag}")
        else:
            st.write("Nenhum red flag destacado.")
        st.subheader("Educação ao paciente")
        for item in response.get("patient_education", []):
            st.write(f"- {item}")
    with tabs[1]:
        st.json(response)
        st.markdown("#### Referências")
        refs = response.get("references", [])
        if refs:
            st.table(refs)
        else:
            st.info("A resposta não retornou referências explícitas.")
    with tabs[2]:
        retrieved = result.get("retrieved_chunks", [])
        if not retrieved:
            st.info("Nenhum documento recuperado do RAG.")
        else:
            for item in retrieved:
                st.markdown(
                    f"**{item.get('title') or 'Documento'}** — {item.get('source') or 'Fonte desconhecida'} ({item.get('year') or 's/ano'})\\n"
                    f"Similaridade: {item.get('similarity'):.2f}\\n"
                    f"Resumo: {item.get('chunk_summary') or 'Sem resumo'}"
                )
            with st.expander("Contexto completo"):
                st.code(result.get("context", ""), language="markdown")
    with tabs[3]:
        st.code(result.get("raw_response", ""), language="json")
        st.caption("Resposta literal retornada pelo modelo antes da validação.")

    # Refinement
    st.markdown("### Refinar triagem")
    with st.form("refine_form"):
        refine_text = st.text_area("Acrescentar informações / Refinar triagem", height=120)
        submitted_refine = st.form_submit_button("Refinar", type="secondary")
    if submitted_refine:
        if not refine_text.strip():
            st.warning("Informe novas informações para refinar.")
        else:
            st.session_state.accumulated_context = "\n".join(
                [
                    part
                    for part in [
                        st.session_state.accumulated_context.strip(),
                        refine_text.strip(),
                    ]
                    if part
                ]
            )
            base_payload = st.session_state.base_payload or {}
            refine_payload = {
                **base_payload,
                "triage_id": triage_id,
                "additional_context": st.session_state.accumulated_context,
            }
            try:
                refined = perform_triage(API_BASE, refine_payload)
            except httpx.HTTPError as exc:
                st.error(f"Falha ao refinar triagem: {exc}")
            else:
                previous_json = st.session_state.last_response_json or ""
                new_json = json.dumps(refined.get("response", {}), ensure_ascii=False, indent=2)
                if previous_json:
                    diff = "\n".join(
                        difflib.unified_diff(
                            previous_json.splitlines(),
                            new_json.splitlines(),
                            fromfile="antes",
                            tofile="depois",
                            lineterm="",
                        )
                    )
                else:
                    diff = new_json
                st.markdown("#### Diferença em relação à resposta anterior")
                st.code(diff or "Sem alterações relevantes", language="diff")
                st.session_state.triage_history.append(refined)
                st.session_state.last_result = refined
                st.session_state.last_response_json = new_json
                st.success("Triagem refinada.")

    st.markdown("### Feedback clínico")
    with st.form("feedback_form"):
        usefulness = st.slider("Utilidade", min_value=1, max_value=5, value=4)
        safety = st.slider("Segurança", min_value=1, max_value=5, value=4)
        accepted = st.checkbox("Aceitei a recomendação na prática", value=True)
        comments = st.text_area("Comentários adicionais", height=80)
        submit_feedback = st.form_submit_button("Enviar feedback")
    if submit_feedback:
        payload = {
            "triage_id": triage_id,
            "usefulness": usefulness,
            "safety": safety,
            "accepted": accepted,
            "comments": comments.strip() or None,
        }
        try:
            resp = send_feedback(API_BASE, payload)
        except httpx.HTTPError as exc:
            st.error(f"Falha ao enviar feedback: {exc}")
        else:
            st.success(resp.get("message", "Feedback registrado."))

    st.markdown("### Histórico de triagens nesta sessão")
    history = st.session_state.triage_history[-5:]
    for item in reversed(history):
        st.write(
            f"- `{item.get('triage_id')}` • Prioridade: **{item.get('response', {}).get('priority')}** • Destino: {item.get('response', {}).get('disposition')}"
        )
else:
    st.info("Preencha o formulário e gere a primeira triagem para visualizar os resultados aqui.")
