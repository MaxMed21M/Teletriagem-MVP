@echo off
setlocal enabledelayedexpansion
if exist .env (
  for /f "usebackq tokens=*" %%i in (".env") do set %%i
)
if not defined UI_PORT set UI_PORT=8501
streamlit run teletriagem/frontend/Home.py --server.port %UI_PORT%
