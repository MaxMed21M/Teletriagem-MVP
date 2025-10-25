from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

import httpx
import streamlit as st

from api_client import (
    create_triage,
    default_api_base,
    export_triage_pec,
    flag_enabled,
    glossary_search,
    list_triages,
    metrics_summary,
    request_ai_refine,
    request_ai_triage,
    review_triage,
)

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
if "last_ai_id" not in st.session_state:
    st.session_state.last_ai_id = None
if "last_review_result" not in st.session_state:
    st.session_state.last_review_result = None

with st.sidebar:
    st.header("Configuração")
    base_url = st.text_input("API base URL", st.session_state.api_base_url).strip()
    if base_url:
        st.session_state.api_base_url = base_url.rstrip("/")
    st.session_state.debug_mode = st.checkbox("Modo DEBUG", value=st.session_state.debug_mode)
    if flag_enabled("AI_GLOSSARIO"):
        query = st.text_input("Glossário (busca)", key="glossary_query")
        if query:
            try:
                gloss = glossary_search(st.session_state.api_base_url, query)
            except httpx.HTTPError as exc:
                st.warning(f"Glossário indisponível: {exc}")
            else:
                st.json(gloss)
    if flag_enabled("AI_METRICS") or flag_enabled("AI_DRIFT_BIAS"):
        if st.button("Atualizar métricas (7d)"):
            try:
                metrics = metrics_summary(st.session_state.api_base_url)
            except httpx.HTTPError as exc:
                st.warning(f"Métricas indisponíveis: {exc}")
            else:
                st.json(metrics)
    st.markdown(
        """
        - API: `python run_all.py`
        - UI: `http://127.0.0.1:8501`
        - Testes: consulte `scripts/test_api.ps1`
        """
    )

API_BASE = st.session_state.api_base_url
DEBUG_MODE = st.session_state.debug_mode
FLAG_HITL = flag_enabled("AI_HITL")
FLAG_EXPORT = flag_enabled("AI_EXPORT_PEC")
FLAG_XAI = flag_enabled("AI_XAI") or flag_enabled("AI_STRICT_JSON")
FLAG_GLOSSARIO = flag_enabled("AI_GLOSSARIO")

DEFAULTS = {
    "patient_name": "Paciente Teste",
    "age": 35,
    "complaint": "Dor no peito há 30 minutos",
    "hr": 88,
    "sbp": 130,
    "dbp": 85,
    "temp": 36.7,
    "spo2": 97,
    "municipality": "Fortaleza",
    "region": "Ceará",
    "season": "chuvoso",
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
    st.markdown("#### Contexto epidemiológico")
    col_geo1, col_geo2, col_geo3 = st.columns(3)
    with col_geo1:
        municipality = st.text_input(
            "Município",
            key=f"{prefix}_municipality",
            value=DEFAULTS.get("municipality", ""),
        )
    with col_geo2:
        region = st.text_input(
            "Região",
            key=f"{prefix}_region",
            value=DEFAULTS.get("region", ""),
        )
    with col_geo3:
        season = st.selectbox(
            "Estação",
            options=["chuvoso", "seco", "indefinido"],
            index=["chuvoso", "seco", "indefinido"].index(
                DEFAULTS.get("season", "chuvoso")
            )
            if DEFAULTS.get("season", "chuvoso") in {"chuvoso", "seco", "indefinido"}
            else 0,
            key=f"{prefix}_season",
        )
    attachments_input = st.text_area(
        "Anexos (um por linha, opcional)",
        key=f"{prefix}_attachments",
        height=80,
    )
    attachments: List[str] = [
        line.strip()
        for line in attachments_input.splitlines()
        if line.strip()
    ]

    payload = {
        "patient_name": patient_name.strip(),
        "age": int(age),
        "complaint": complaint.strip(),
        "vitals": vitals,
        "municipality": municipality.strip() or None,
        "region": region.strip() or None,
        "season": season.strip() or None,
        "attachments": attachments,
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
        col_form1, col_form2 = st.columns(2)
        with col_form1:
            natural_mode = st.checkbox("Entrada em linguagem natural", key="ai_nl_mode")
        with col_form2:
            author = st.text_input("Autor da solicitação", value="UI Streamlit", key="ai_author")
        if natural_mode:
            ai_payload["natural_input"] = st.text_area(
                "Descreva o caso em texto livre",
                key="ai_natural_input",
                height=150,
            )
        if author.strip():
            ai_payload["author"] = author.strip()
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
                        payload_json = response.json()
                        st.session_state.last_ai_response = payload_json
                        st.session_state.last_ai_error = None
                        st.session_state.last_ai_id = payload_json.get("id")
                    except ValueError:
                        st.session_state.last_ai_response = None
                        st.session_state.last_ai_error = "Resposta não é JSON válido."
    if st.session_state.last_ai_error:
        st.error(st.session_state.last_ai_error)
    if st.session_state.last_ai_status is not None:
        st.info(f"Status da última requisição: {st.session_state.last_ai_status}")

    result = st.session_state.last_ai_response
    if result is not None:
        header_cols = st.columns(3)
        header_cols[0].metric(
            "Double-check",
            "Ativo" if result.get("double_check_applied") else "Inativo",
        )
        header_cols[1].metric("Audit ID", result.get("audit_id", "-"))
        header_cols[2].metric("Versão", result.get("version", {}).get("number", 1))
        tabs = st.tabs(["Estruturado", "Texto do modelo", "JSON bruto"])
        parsed = result.get("parsed") if isinstance(result, dict) else None
        parse_error = result.get("parse_error") if isinstance(result, dict) else None

        with tabs[0]:
            if parsed:
                cols = st.columns(3)
                cols[0].metric("Prioridade", parsed.get("priority", "-"))
                cols[1].metric("Disposição", parsed.get("disposition", "-"))
                latency = result.get("latency_ms")
                if latency is not None:
                    suffix = " ⚠️" if result.get("latency_warning") else ""
                    cols[2].metric("Latência", f"{latency} ms{suffix}")

                confidence = parsed.get("confidence")
                if isinstance(confidence, dict):
                    st.markdown("#### Confiança (0 a 1)")
                    conf_cols = st.columns(4)
                    keys = ["overall", "priority", "probable_causes", "recommended_actions"]
                    labels = ["Geral", "Prioridade", "Causas", "Condutas"]
                    for idx, key in enumerate(keys):
                        value = float(confidence.get(key, 0.0))
                        value = max(0.0, min(1.0, value))
                        conf_cols[idx].progress(value)
                        conf_cols[idx].caption(f"{labels[idx]}: {value*100:.1f}%")

                if parsed.get("rationale"):
                    st.info(parsed.get("rationale"))

                fallback_notice = parsed.get("fallback_notice") or result.get("fallback_notice")
                if fallback_notice:
                    st.warning(fallback_notice)

                epi = parsed.get("epidemiology_context")
                if epi:
                    with st.expander("Contexto epidemiológico", expanded=False):
                        st.json(epi)

                crosscheck = parsed.get("crosscheck") or {}
                if crosscheck.get("missing"):
                    st.error(
                        "Red flags esperadas não foram cobertas: "
                        + ", ".join(crosscheck["missing"])
                    )

                attachments = parsed.get("attachments") or result.get("attachments") or []
                if attachments:
                    with st.expander("Anexos registrados", expanded=False):
                        for name in attachments:
                            st.markdown(f"- {name}")

                if FLAG_XAI:
                    explanations = parsed.get("explanations") or []
                    if explanations:
                        st.markdown("#### Explicações da IA")
                        for item in explanations:
                            st.markdown(f"- {item}")

                    questions = parsed.get("required_next_questions") or []
                    if questions:
                        st.markdown("#### Perguntas de follow-up")
                        for item in questions:
                            st.markdown(f"- {item}")

                    uncertainty = parsed.get("uncertainty_flags") or []
                    if uncertainty:
                        st.warning("\n".join(f"⚠️ {item}" for item in uncertainty))

                if FLAG_GLOSSARIO and parsed.get("normalized_terms"):
                    st.markdown("#### Termos normalizados")
                    for term in parsed["normalized_terms"]:
                        st.markdown(
                            f"- `{term.get('matched')}` → `{term.get('clinical_equivalent')}` "
                            f"(CID-10: {', '.join(term.get('cid10', [])) or 'N/A'})"
                        )

                if parsed.get("cid10_candidates"):
                    st.markdown("#### CID-10 sugeridos")
                    st.write(", ".join(parsed["cid10_candidates"]))

                pec_block = parsed.get("pec_export")
                if pec_block:
                    with st.expander("Prévia para PEC", expanded=False):
                        st.json(pec_block)

                version_info = result.get("version") or parsed.get("version")
                if version_info:
                    st.markdown("#### Versão da triagem")
                    st.write(version_info)
                versions_history = result.get("versions") or []
                if versions_history:
                    with st.expander("Histórico de versões", expanded=False):
                        for entry in versions_history:
                            st.markdown(
                                f"**Versão {entry['version']['number']}** — {entry['version']['timestamp']}"
                            )
                            st.json(entry.get("parsed"))
                            if entry.get("refinement_text"):
                                st.caption(f"Refinamento: {entry['refinement_text']}")
                            st.markdown("---")

                st.markdown("#### JSON estruturado")
                st.json(parsed)
            else:
                st.warning(parse_error or "Parser retornou dados vazios.")
        with tabs[1]:
            st.code(result.get("model_text", ""), language="markdown")
        with tabs[2]:
            st.json(result)

        st.markdown("### 🔄 Refinar triagem")
        refine_col1, refine_col2 = st.columns([3, 1])
        with refine_col1:
            refinement_text = st.text_area(
                "Adicione novas informações ou correções:",
                key="refinement_text",
                height=120,
            )
        with refine_col2:
            reviewer_name = st.text_input("Revisor", value="UI Streamlit", key="refine_author")
        if st.button("Atualizar triagem", key="refine_button", disabled=not st.session_state.last_ai_id):
            if not refinement_text.strip():
                st.warning("Informe detalhes para o refinamento.")
            else:
                with st.spinner("Enviando refinamento..."):
                    try:
                        refine_response = request_ai_refine(
                            API_BASE,
                            st.session_state.last_ai_id,
                            refinement_text.strip(),
                            reviewer_name.strip() or None,
                        )
                    except httpx.HTTPError as exc:
                        st.error(f"Falha no refinamento: {exc}")
                    else:
                        st.session_state.last_ai_status = refine_response.status_code
                        try:
                            payload_json = refine_response.json()
                        except ValueError:
                            st.session_state.last_ai_error = "Resposta do refinamento não é JSON."
                        else:
                            st.session_state.last_ai_response = payload_json
                            st.session_state.last_ai_error = None
                            st.session_state.last_ai_id = payload_json.get("id", st.session_state.last_ai_id)
                            st.success("Refinamento processado com sucesso.")

        if FLAG_HITL and st.session_state.last_ai_id:
            review_info = result.get("review") or {}
            st.markdown("### Revisão humana (HITL)")
            st.info(f"Status atual: {review_info.get('status', 'pending')}")
            review_notes = st.text_area("Motivo (override/rejeição)", key="hitl_notes")
            col_priority, col_disposition = st.columns(2)
            suggested_priority = (parsed or {}).get("priority", "non-urgent")
            suggested_disposition = (parsed or {}).get("disposition", "home care")
            final_priority = col_priority.selectbox(
                "Prioridade final",
                options=["emergent", "urgent", "non-urgent"],
                index=["emergent", "urgent", "non-urgent"].index(suggested_priority)
                if suggested_priority in {"emergent", "urgent", "non-urgent"}
                else 2,
            )
            disposition_options = ["refer ER", "schedule visit", "home care"]
            final_disposition = col_disposition.selectbox(
                "Conduta final",
                options=disposition_options,
                index=disposition_options.index(suggested_disposition)
                if suggested_disposition in disposition_options
                else 2,
            )
            reviewer_name = st.text_input("Revisor", value="UI Streamlit")
            hitl_cols = st.columns(3)
            if hitl_cols[0].button("Aceitar IA", key="hitl_accept"):
                try:
                    result_review = review_triage(
                        API_BASE,
                        st.session_state.last_ai_id,
                        {"action": "accept", "reviewer": reviewer_name},
                    )
                except httpx.HTTPError as exc:
                    st.error(f"Falha ao aceitar: {exc}")
                else:
                    st.session_state.last_review_result = result_review
                    st.success("Triagem aceita.")
            if hitl_cols[1].button("Override", key="hitl_override"):
                try:
                    result_review = review_triage(
                        API_BASE,
                        st.session_state.last_ai_id,
                        {
                            "action": "override",
                            "notes": review_notes,
                            "reviewer": reviewer_name,
                            "final_priority": final_priority,
                            "final_disposition": final_disposition,
                        },
                    )
                except httpx.HTTPError as exc:
                    st.error(f"Falha no override: {exc}")
                else:
                    st.session_state.last_review_result = result_review
                    st.success("Override registrado.")
            if hitl_cols[2].button("Rejeitar", key="hitl_reject"):
                try:
                    result_review = review_triage(
                        API_BASE,
                        st.session_state.last_ai_id,
                        {
                            "action": "reject",
                            "notes": review_notes,
                            "reviewer": reviewer_name,
                        },
                    )
                except httpx.HTTPError as exc:
                    st.error(f"Falha ao rejeitar: {exc}")
                else:
                    st.session_state.last_review_result = result_review
                    st.warning("Triagem rejeitada.")

        if st.session_state.last_review_result:
            with st.expander("Última revisão", expanded=False):
                st.json(st.session_state.last_review_result)

        if FLAG_EXPORT and st.session_state.last_ai_id:
            if st.button("Exportar para PEC (preview)"):
                try:
                    export_payload = export_triage_pec(API_BASE, st.session_state.last_ai_id)
                except httpx.HTTPError as exc:
                    st.error(f"Exportação indisponível: {exc}")
                else:
                    st.json(export_payload)

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
    if flag_enabled("AI_METRICS"):
        if st.button("Atualizar painel epidemiológico", key="epi_panel_btn"):
            try:
                epi_metrics = metrics_summary(API_BASE)
            except httpx.HTTPError as exc:
                st.error(f"Painel epidemiológico indisponível: {exc}")
            else:
                epidemiology = epi_metrics.get("epidemiology", {})
                with st.expander("Sinais epidemiológicos (7d)", expanded=True):
                    weekly = epidemiology.get("weekly") or {}
                    if weekly:
                        st.bar_chart(list(weekly.values()))
                        st.caption(", ".join(f"{k}: {v}" for k, v in weekly.items()))
                    complaints = epidemiology.get("complaints") or []
                    if complaints:
                        st.write("Principais queixas:")
                        st.table(complaints)
                    municipalities = epidemiology.get("municipalities") or []
                    if municipalities:
                        st.write("Municípios:")
                        st.table(municipalities)
