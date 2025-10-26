#!/usr/bin/env python3
"""Start the Teletriagem API (Uvicorn) and the Streamlit UI."""

import argparse
import os
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parent

API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "8000"))
UI_PORT = int(os.getenv("UI_PORT", "8501"))
API_BASE = os.getenv("TELETRIAGEM_API_BASE", f"http://{API_HOST}:{API_PORT}")
OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

UVICORN_CMD = [
    "uvicorn",
    "backend.app.main:app",
    "--host",
    API_HOST,
    "--port",
    str(API_PORT),
]
STREAMLIT_CMD = [
    "streamlit",
    "run",
    "ui/home.py",
    "--server.port",
    str(UI_PORT),
    "--server.headless",
    "true",
]


def _print_box(message: str) -> None:
    border = "═" * (len(message) + 2)
    print(f"\n╔{border}╗")
    print(f"║ {message} ║")
    print(f"╚{border}╝\n")


def wait_for_http(url: str, timeout: float = 30.0, expect_json: bool = False) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            req = Request(url, headers={"User-Agent": "teletriagem-runner/1.0"})
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Executa API (Uvicorn) e UI (Streamlit)")
    parser.add_argument("--lite", action="store_true", help="Executa somente a API FastAPI")
    parser.add_argument("--no-browser", action="store_true", help="Não abre o navegador automaticamente")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    mode = "API (modo lite)" if args.lite else "API + UI"
    _print_box(f"Iniciando Teletriagem — {mode}")

    if not wait_for_http(f"{OLLAMA_URL.rstrip('/')}/api/tags", timeout=5.0):
        print(
            "⚠️  Ollama não respondeu rapidamente. O endpoint /api/triage/ai pode usar o fallback até o serviço iniciar."
        )

    print("▶️  Iniciando FastAPI (uvicorn)...")
    api_proc = start_process(UVICORN_CMD)

    if wait_for_http(f"{API_BASE.rstrip('/')}/healthz", timeout=60.0, expect_json=True):
        print(f"✅ API disponível em {API_BASE.rstrip('/')}")
    else:
        print("❌ API não respondeu ao health check dentro do timeout.")

    ui_proc: subprocess.Popen | None = None
    if not args.lite:
        print("▶️  Iniciando UI (Streamlit)...")
        ui_proc = start_process(STREAMLIT_CMD)
        ui_url = f"http://127.0.0.1:{UI_PORT}"
        if wait_for_http(ui_url, timeout=60.0):
            print(f"✅ UI disponível em {ui_url}")
            if not args.no_browser:
                try:
                    webbrowser.open(ui_url, new=2)
                except Exception:
                    pass
        else:
            print("❌ UI não respondeu dentro do timeout. Consulte os logs do Streamlit.")
        _print_box("Teletriagem em execução. Pressione Ctrl+C para encerrar.")
    else:
        _print_box("API em execução (modo lite). Pressione Ctrl+C para encerrar.")

    try:
        while True:
            api_exit = api_proc.poll()
            ui_exit = ui_proc.poll() if ui_proc is not None else None
            if api_exit is not None:
                print(f"⚠️ API finalizada com código {api_exit}. Encerrando demais processos...")
                break
            if ui_proc is not None and ui_exit is not None:
                print(f"⚠️ UI finalizada com código {ui_exit}. Encerrando API...")
                break
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n🧹 Encerrando...")

    for proc, name in ((ui_proc, "UI"), (api_proc, "API")):
        if proc is None or proc.poll() is not None:
            continue
        try:
            if os.name == "nt":
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                proc.terminate()
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        except Exception:
            pass
        print(f"⏹  {name} encerrada.")

    print("✅ Finalizado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
