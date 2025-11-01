"""Render export buttons for PEC and FHIR."""
from __future__ import annotations

import asyncio
import streamlit as st

from ..utils import api_client


def render_exports(case_id: int | None) -> None:
    st.subheader("Exportações")
    if case_id is None:
        st.info("Realize uma triagem para habilitar exportações.")
        return
    col1, col2 = st.columns(2)
    if col1.button("Exportar PEC/e-SUS"):
        result = asyncio.run(api_client.export_pec(case_id))
        st.success(f"Arquivo gerado: {result['path']}")
    if col2.button("Exportar FHIR"):
        result = asyncio.run(api_client.export_fhir(case_id))
        st.success(f"Bundle gerado: {result['path']}")
