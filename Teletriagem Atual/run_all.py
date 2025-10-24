#!/usr/bin/env python3
"""
Run All: starts FastAPI (Uvicorn) + Streamlit, checks health, and opens the UI.
Place this file at the ROOT of the project and run:  python run_all.py
"""

import os
import sys
import time
import signal
import subprocess
import webbrowser
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

PROJECT_ROOT = Path(__file__).resolve().parent

# ---- Config (env or defaults) ----
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "8000"))
UI_PORT = int(os.getenv("UI_PORT", "8501"))
TELETRIAGEM_API_BASE = os.getenv("TELETRIAGEM_API_BASE", f"http://{API_HOST}:{API_PORT}")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")

UVICORN_CMD = ["uvicorn", "backend.app.main:app", "--reload", "--host", API_HOST, "--port", str(API_PORT)]
STREAMLIT_CMD = ["streamlit", "run", "frontend/home.py", "--server.port", str(UI_PORT), "--server.headless", "true"]

def _print_box(msg: str):
    line = "═" * (len(msg) + 2)
    print(f"\n╔{line}╗")
    print(f"║ {msg} ║")
    print(f"╚{line}╝\n")

def wait_for_http(url: str, timeout: float = 60.0, expect_json: bool = False) -> bool:
    """Poll an HTTP URL until it responds or timeout."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            req = Request(url, headers={"User-Agent": "run_all/1.0"})
            with urlopen(req, timeout=5) as resp:
                if expect_json:
                    _ = resp.read(64)
                return True
        except URLError:
            time.sleep(0.5)
        except Exception:
            time.sleep(0.5)
    return False

def start_process(cmd: list[str]) -> subprocess.Popen:
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen(cmd, cwd=str(PROJECT_ROOT), creationflags=creationflags)

def main() -> int:
    _print_box("Iniciando Teletriagem: API (FastAPI/Uvicorn) + UI (Streamlit)")

    # 1) Check Ollama (soft check)
    ollama_ok = wait_for_http(f"{OLLAMA_URL}/api/tags", timeout=5.0)
    if not ollama_ok:
        print(f"⚠️  Aviso: Ollama não respondeu em {OLLAMA_URL}. Verifique se está em execução.\n"
              f"    O backend pode falhar nas chamadas de IA até o Ollama iniciar.")

    # 2) Start Uvicorn (API)
    print("▶️  Iniciando API (Uvicorn)...")
    api_proc = start_process(UVICORN_CMD)

    # 3) Wait API health
    api_health_ok = wait_for_http(f"{TELETRIAGEM_API_BASE}/health", timeout=60.0, expect_json=True)
    if api_health_ok:
        print(f"✅ API pronta em {TELETRIAGEM_API_BASE}")
    else:
        print(f"❌ API não respondeu em {TELETRIAGEM_API_BASE}/health dentro do timeout.")

    # 4) Start Streamlit (UI)
    print("▶️  Iniciando UI (Streamlit)...")
    ui_proc = start_process(STREAMLIT_CMD)

    # 5) Wait UI
    ui_ok = wait_for_http(f"http://127.0.0.1:{UI_PORT}", timeout=60.0)
    ui_url = f"http://127.0.0.1:{UI_PORT}"
    if ui_ok:
        print(f"✅ UI pronta em {ui_url}")
        try:
            webbrowser.open(ui_url, new=2)
        except Exception:
            pass
    else:
        print(f"❌ UI não respondeu em {ui_url} dentro do timeout. Veja os logs.")

    _print_box("Teletriagem em execução. Pressione Ctrl+C para encerrar.")

    try:
        while True:
            api_ret = api_proc.poll()
            ui_ret = ui_proc.poll()
            if api_ret is not None:
                print(f"⚠️ API finalizou com código {api_ret}. Encerrando UI...")
                break
            if ui_ret is not None:
                print(f"⚠️ UI finalizou com código {ui_ret}. Encerrando API...")
                break
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n🧹 Encerrando...")

    for proc, name in [(ui_proc, "UI"), (api_proc, "API")]:
        if proc and proc.poll() is None:
            try:
                if os.name == "nt":
                    proc.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
            except Exception:
                pass
            print(f"⏹  {name} encerrada.")

    print("✅ Finalizado.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
