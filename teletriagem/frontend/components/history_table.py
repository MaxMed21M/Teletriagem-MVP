"""Component that renders triage history table."""
from __future__ import annotations

from typing import List

import pandas as pd
import streamlit as st


def render_history(history: List[dict]) -> None:
    st.subheader("Histórico de triagens")
    if not history:
        st.info("Nenhum caso registrado ainda.")
        return
    df = pd.DataFrame(history)
    st.dataframe(df, use_container_width=True)
