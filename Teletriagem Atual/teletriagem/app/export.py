"""Offline export utilities for triage results."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from loguru import logger
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from .log import scrub_payload


def export_json(result: Dict, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("triage_json_export", path=str(destination))
    return destination


def export_pdf(result: Dict, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    sanitized = scrub_payload(result)
    pdf = canvas.Canvas(str(destination), pagesize=A4)
    width, height = A4
    text = pdf.beginText(20 * mm, height - 30 * mm)
    text.setFont("Helvetica", 12)
    text.textLine("Teletriagem - Resumo de Atendimento")
    text.textLine("")
    for key in ["triage_level", "priority_score", "summary"]:
        if key in sanitized:
            text.textLine(f"{key}: {sanitized[key]}")
    text.textLine("")
    if "recommendations" in sanitized:
        text.textLine("Recomendações:")
        for item in sanitized["recommendations"]:
            text.textLine(f" - {item}")
    if "risk_flags" in sanitized:
        text.textLine("")
        text.textLine("Flags de risco:")
        for item in sanitized["risk_flags"]:
            text.textLine(f" - {item}")
    pdf.drawText(text)
    pdf.showPage()
    pdf.save()
    logger.info("triage_pdf_export", path=str(destination))
    return destination


__all__ = ["export_json", "export_pdf"]
