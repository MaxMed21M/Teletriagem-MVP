"""Streamlit UI for Teletriagem with async polling."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, Optional

import httpx
import streamlit as st

from .config import get_settings
from .export import export_json, export_pdf

settings = get_settings()
API_BASE = f"http://localhost:{settings.app_port}/api"


def _default_payload() -> Dict:
    return {
        "patient_name": "Paciente Teste",
        "age": 45,
        "sex": "masculino",
        "complaint": "dor torácica",
        "history": "hipertenso, começou há 30 minutos",
        "medications": "AAS 100mg",
        "allergies": "nenhuma",
        "vitals": {
            "heart_rate": 110,
            "respiratory_rate": 24,
            "systolic_bp": 100,
            "diastolic_bp": 60,
            "temperature": 37.2,
            "spo2": 94,
        },
    }


def _poll_status(triage_id: str, client: httpx.Client) -> Optional[Dict]:
    for _ in range(120):
        response = client.get(f"{API_BASE}/triage/status/{triage_id}", timeout=5)
        response.raise_for_status()
        data = response.json()
        if data.get("status") == "COMPLETO":
            return data
        time.sleep(1)
    return None


def render() -> None:
    st.set_page_config(page_title="Teletriagem Offline", layout="wide")
    st.title("Teletriagem Offline")
    st.caption("Operação 100% offline com ensemble clínico + IA local")

    with st.sidebar:
        st.header("Configuração")
        st.write(f"Modelo primário: {settings.model_primary}")
        st.write(f"Fallback: {settings.model_fallback}")
        st.write(f"Timeout IA: {settings.inference_timeout_ms} ms")
        benchmark = st.button("Benchmark", use_container_width=True)
        export_dir = st.text_input("Diretório de exportação", value="exports")

    payload_state = st.session_state.setdefault("payload", _default_payload())

    with st.form("triage_form"):
        st.subheader("Dados do paciente")
        payload_state["patient_name"] = st.text_input("Nome", payload_state["patient_name"])
        col1, col2, col3 = st.columns(3)
        payload_state["age"] = col1.number_input("Idade", min_value=0, max_value=120, value=int(payload_state["age"]))
        payload_state["sex"] = col2.selectbox("Sexo", ["masculino", "feminino", "outro"], index=["masculino", "feminino", "outro"].index(payload_state["sex"]))
        payload_state["complaint"] = st.text_area("Queixa principal", payload_state["complaint"])
        payload_state["history"] = st.text_area("História", payload_state["history"])
        payload_state["medications"] = st.text_area("Medicações", payload_state["medications"])
        payload_state["allergies"] = st.text_input("Alergias", payload_state["allergies"])

        st.subheader("Sinais vitais")
        vitals = payload_state.setdefault("vitals", {})
        v_col1, v_col2, v_col3 = st.columns(3)
        vitals["heart_rate"] = v_col1.number_input("FC", min_value=20, max_value=250, value=int(vitals.get("heart_rate", 80)))
        vitals["respiratory_rate"] = v_col2.number_input("FR", min_value=5, max_value=80, value=int(vitals.get("respiratory_rate", 16)))
        vitals["systolic_bp"] = v_col3.number_input("PAS", min_value=50, max_value=260, value=int(vitals.get("systolic_bp", 120)))
        v_col4, v_col5, v_col6 = st.columns(3)
        vitals["diastolic_bp"] = v_col4.number_input("PAD", min_value=30, max_value=200, value=int(vitals.get("diastolic_bp", 80)))
        vitals["temperature"] = v_col5.number_input("Temp (°C)", min_value=30.0, max_value=43.0, value=float(vitals.get("temperature", 36.5)), step=0.1)
        vitals["spo2"] = v_col6.number_input("SpO2", min_value=50, max_value=100, value=int(vitals.get("spo2", 98)))

        submitted = st.form_submit_button("Enviar triagem", use_container_width=True)

    if submitted:
        with httpx.Client() as client:
            with st.spinner("Enviando triagem..."):
                response = client.post(f"{API_BASE}/triage", json=payload_state, timeout=5)
                response.raise_for_status()
                data = response.json()
                triage_id = data["triage_id"]
            st.success(f"Triagem registrada: {triage_id}")
            with st.spinner("Processando..."):
                result = _poll_status(triage_id, client)
        if not result:
            st.error("Tempo excedido aguardando resultado")
        else:
            st.session_state["last_result"] = result
            st.experimental_rerun()

    result = st.session_state.get("last_result")
    if result:
        st.subheader("Resultado")
        st.json(result)
        manual_level = st.selectbox(
            "Ajustar nível manualmente",
            ["nenhum", "emergencia", "urgencia", "observacao", "rotina"],
            index=0,
        )
        if manual_level != "nenhum" and st.button("Aplicar ajuste"):
            with httpx.Client() as client:
                response = client.post(
                    f"{API_BASE}/triage/{result['triage_id']}/override",
                    json={"triage_level": manual_level},
                    timeout=5,
                )
            if response.status_code == 200:
                st.success(f"Calibração atualizada: {response.json()['weights']}")
            else:
                st.error(f"Falha na calibração: {response.text}")
        export_path = Path(export_dir)
        col_export1, col_export2 = st.columns(2)
        if col_export1.button("Exportar JSON"):
            path = export_json(result, export_path / f"{result['triage_id']}.json")
            st.success(f"Exportado para {path}")
        if settings.enable_pdf_export and col_export2.button("Exportar PDF"):
            path = export_pdf(result, export_path / f"{result['triage_id']}.pdf")
            st.success(f"PDF salvo em {path}")

    if benchmark:
        st.subheader("Benchmark local")
        output = _run_benchmark()
        st.code(output)


def _run_benchmark() -> str:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "bench_local.py"
    if not script_path.exists():
        return "Script de benchmark não encontrado"
    import subprocess

    result = subprocess.run(["python", str(script_path)], capture_output=True, text=True)
    if result.returncode != 0:
        return result.stderr
    return result.stdout


if __name__ == "__main__":
    render()
