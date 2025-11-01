@echo off
setlocal enabledelayedexpansion
if exist .env (
  for /f "usebackq tokens=*" %%i in (".env") do set %%i
)
if not defined API_HOST set API_HOST=127.0.0.1
if not defined API_PORT set API_PORT=8000
uvicorn teletriagem.api.main:app --host %API_HOST% --port %API_PORT% --reload
