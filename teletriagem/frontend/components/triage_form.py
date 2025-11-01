"""Streamlit form for capturing triage input."""
from __future__ import annotations

import streamlit as st


def render_triage_form() -> dict | None:
    with st.form("triage_form"):
        st.subheader("Dados do Paciente")
        col1, col2 = st.columns(2)
        age = col1.number_input("Idade", min_value=0, max_value=120, value=30)
        sex = col2.selectbox("Sexo", ["male", "female", "other"], index=0)
        chief_complaint = st.text_area("Queixa principal", "Dor no peito")
        symptoms_duration = st.text_input("Tempo de sintomas", "2 horas")
        comorbidities = st.text_area("Comorbidades", "Hipertensão")
        medications = st.text_area("Medicações", "Losartana")
        allergies = st.text_area("Alergias", "Nenhuma")
        notes = st.text_area("Notas adicionais", "")

        st.markdown("### Sinais Vitais")
        col_v1, col_v2, col_v3 = st.columns(3)
        systolic = col_v1.number_input("PAS", value=120, min_value=40, max_value=260)
        diastolic = col_v1.number_input("PAD", value=80, min_value=20, max_value=180)
        heart_rate = col_v2.number_input("FC", value=80, min_value=20, max_value=240)
        resp_rate = col_v2.number_input("FR", value=16, min_value=5, max_value=80)
        temperature = col_v3.number_input("Temperatura (°C)", value=36.5, min_value=30.0, max_value=43.0, step=0.1)
        spo2 = col_v3.number_input("SpO₂", value=97, min_value=40, max_value=100)

        submitted = st.form_submit_button("Triar")
        if submitted:
            return {
                "age": age,
                "sex": sex,
                "chief_complaint": chief_complaint,
                "symptoms_duration": symptoms_duration,
                "comorbidities": comorbidities,
                "medications": medications,
                "allergies": allergies,
                "notes": notes,
                "vitals": {
                    "systolic_bp": systolic,
                    "diastolic_bp": diastolic,
                    "heart_rate": heart_rate,
                    "respiratory_rate": resp_rate,
                    "temperature_c": temperature,
                    "spo2": spo2,
                },
            }
    return None
