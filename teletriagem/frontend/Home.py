"""Streamlit entrypoint for the Teletriagem MVP."""
from __future__ import annotations

import asyncio
import streamlit as st

from .components import export_panel, history_table, triage_form
from .utils import api_client, state

st.set_page_config(page_title="Teletriagem", layout="wide")
st.title("Teletriagem Médica - MVP")
st.caption("Ferramenta de apoio. Não substitui avaliação médica presencial.")

triage_state = state.get_state(st.session_state)

col_form, col_result, col_history = st.columns([1.2, 1.0, 1.0])

with col_form:
    payload = triage_form.render_triage_form()
    if payload:
        with st.spinner("Consultando assistente clínico..."):
            response = asyncio.run(api_client.create_triage(payload))
        triage_state.last_result = response["result"]
        triage_state.last_case_id = response["case_id"]
        triage_state.history = asyncio.run(api_client.list_cases())
        st.success("Triagem concluída. Veja os resultados ao lado.")

with col_result:
    st.subheader("Resultado")
    if triage_state.last_result:
        result = triage_state.last_result
        st.markdown(f"**Prioridade:** {result['priority']}")
        st.write("### Red Flags")
        st.write("\n".join(f"- {flag}" for flag in result.get("red_flags", [])))
        st.write("### Ações Recomendadas")
        st.write("\n".join(f"- {action}" for action in result.get("recommended_actions", [])))
        st.write("### SOAP")
        st.json(result.get("soap", {}))
        st.write("### Avisos")
        st.write("\n".join(result.get("warnings", [])))
        st.info("Este conteúdo é informativo e não substitui o julgamento clínico.")

        refine_text = st.text_area("Adicionar informação para refinamento")
        if st.button("Refinar triagem") and refine_text:
            case_id = triage_state.last_case_id
            if case_id is None:
                st.warning("Nenhum caso para refinar.")
            else:
                with st.spinner("Reprocessando..."):
                    response = asyncio.run(api_client.refine_triage(case_id, refine_text))
                triage_state.last_result = response["result"]
                triage_state.last_case_id = response["case_id"]
                triage_state.history = asyncio.run(api_client.list_cases())
                st.success("Triagem refinada.")

        export_panel.render_exports(triage_state.last_case_id)
    else:
        st.info("Envie uma triagem para ver o resultado.")

with col_history:
    st.subheader("Histórico")
    if st.button("Atualizar histórico"):
        triage_state.history = asyncio.run(api_client.list_cases())
    if triage_state.history:
        history_table.render_history(triage_state.history)
    else:
        st.caption("Sem casos carregados. Clique em 'Atualizar histórico'.")
