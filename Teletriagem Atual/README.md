# Teletriagem Resolutiva — MVP 2025

Plataforma de triagem clínica com backend FastAPI, frontend Streamlit e orquestração
via modelo local do Ollama. O objetivo é entregar respostas estruturadas e seguras
no esquema **triage-ai-v1**, com guardrails clínicos e suporte a RAG.

## Visão geral

- **Backend**: FastAPI com validação Pydantic, guardrails e fallback seguro;
- **LLM**: modelo `teletriagem-3b` criado a partir de `llama3.2:3b-instruct`;
- **RAG**: base local em SQLite (`kb.sqlite`) construída a partir de PDFs em `./kb_docs`;
- **Frontend**: Streamlit com refinamento iterativo, diff entre respostas e envio de feedback;
- **Observabilidade**: `/healthz`, `/metrics`, logs estruturados em `./logs` e dataset de ouro
  para curadoria contínua (`gold_examples.jsonl`).

## Requisitos

- Python 3.12
- [Ollama](https://ollama.com/) rodando localmente (CPU suficiente para modelos 3B)
- Modelos `llama3.2:3b-instruct` e `nomic-embed-text` baixados
- Dependências Python (ver `requirements.txt`)

## Configuração inicial

1. **Ambiente virtual e dependências**
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Variáveis de ambiente**
   Um arquivo `.env` já é fornecido com as configurações principais:
   ```env
   LLM_PROVIDER=ollama
   LLM_MODEL=teletriagem-3b
   LLM_TEMPERATURE=0.2
   LLM_TOP_P=0.9
   LLM_NUM_CTX=4096
   LLM_REPEAT_PENALTY=1.18

   RAG_DOCS_PATH=./kb_docs
   RAG_DB_PATH=./kb.sqlite
   RAG_TOP_K=6
   RAG_MAX_CONTEXT_TOKENS=1500

   FALLBACK_ENABLED=true
   RATE_LIMIT_PER_MIN=20
   LOG_PATH=./logs
   ```

3. **Criar o modelo personalizado no Ollama**
   ```bash
   ollama pull llama3.2:3b-instruct
   ollama pull nomic-embed-text
   ollama create teletriagem-3b -f Modelfile
   ```

## Ingestão da base de conhecimento (RAG)

Coloque os PDFs clínicos em `./kb_docs` e execute:

```bash
python scripts/ingest_kb.py --path ./kb_docs
```

O script gera embeddings com `nomic-embed-text`, cria/atualiza `kb.sqlite`, evita reprocessar
arquivos já ingeridos (checksum SHA-256) e registra logs em `logs/ingest_kb.log`.

## Executando o MVP

```bash
python run_all.py
```

O comando inicia o backend (`uvicorn backend.app.main:app`) e a interface Streamlit.
- API: http://127.0.0.1:8000
- UI:  http://127.0.0.1:8501

Use `python run_all.py --lite` para subir apenas a API.

### Endpoints principais

- `POST /api/triage` — orquestra a triagem com RAG, validação e guardrails;
- `POST /api/triage/feedback` — registra avaliação clínica e alimenta dataset de ouro;
- `GET /healthz` — status do modelo, versão de prompt, média de latência e % de JSON válido;
- `GET /metrics` — contadores básicos (requisições, guardrails, fallback).

## Fluxo da interface Streamlit

1. Preencha dados do paciente (queixa, história, sinais vitais) e acione **Gerar triagem**;
2. Revise o JSON estruturado, ações recomendadas e referências RAG;
3. Use **Refinar triagem** para acrescentar novas informações — a UI mostra o diff entre
   a resposta anterior e a atual;
4. Faça download do JSON completo ou envie feedback (utilidade/segurança, comentários,
   marcação de aceitação clínica).

## Guardrails clínicos implementados

- **SpO₂ < 92%** força prioridade `emergent` e disposição `ER`;
- **Dor torácica + sudorese + FC > 100 bpm** força encaminhamento emergencial;
- Presença de `red_flags` impede classificação `non-urgent`;
- Fallback seguro garante JSON válido mesmo em caso de erro na resposta do modelo.

## Observabilidade

- Logs estruturados (`logs/triage_events.log`) com prompt, contexto, resposta e métricas;
- `/healthz` fornece visão rápida do status e qualidade do JSON;
- `/metrics` expõe contadores simples em JSON;
- Feedbacks aceitos com utilidade ≥ 4 são adicionados a `gold_examples.jsonl` para curadoria.

## Testes recomendados

1. **Health check**
   ```bash
   curl http://127.0.0.1:8000/healthz
   ```
2. **Triagem sentinela** (ex.: dor torácica + SpO₂ 89%)
   ```bash
   http POST http://127.0.0.1:8000/api/triage \
     complaint="Dor no peito com sudorese" age:=58 sex=male \
     vitals:='{"heart_rate":110,"spo2":89}'
   ```
3. **Feedback**
   ```bash
   http POST http://127.0.0.1:8000/api/triage/feedback \
     triage_id=<id> usefulness:=5 safety:=5 accepted:=true
   ```

## Troubleshooting

- **Erro ao chamar Ollama**: confirme `OLLAMA_BASE_URL` e se o modelo `teletriagem-3b` está criado.
- **RAG vazio**: execute novamente `python scripts/ingest_kb.py` e verifique `kb.sqlite`.
- **JSON inválido**: consulte `/healthz` para ver taxa de sucesso; logs detalhados ficam em
  `logs/triage_events.log`.

---

Projeto alinhado à diretriz “Teletriagem Resolutiva (versão 2025)” com foco em segurança clínica
sem treino adicional de pesos.
