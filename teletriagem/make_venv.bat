@echo off
python -m venv .venv
call .venv\Scripts\activate.bat
pip install --upgrade pip
pip install -r teletriagem/requirements.txt
