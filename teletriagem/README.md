# Teletriagem MVP

MVP local para teletriagem com FastAPI (backend), Streamlit (frontend) e SQLite. O fluxo contempla triagem, refinamento, histórico, RAG local e exportações PEC/FHIR.

## Pré-requisitos

* Python 3.11+
* Ambiente virtual recomendado (`./make_venv.sh` cria e instala dependências locais se disponíveis)
* Opcional: servidor LLM compatível (Ollama/OpenAI/OpenRouter)

## Configuração rápida

1. Gere um ambiente virtual e instale dependências:
   ```bash
   ./make_venv.sh
   source .venv/bin/activate
   ```
2. Copie o arquivo de variáveis e personalize:
   ```bash
   cp teletriagem/.env.sample teletriagem/.env
   ```
   Ajuste especialmente `LLM_PROVIDER`, `LLM_MODEL` e credenciais.
3. (Opcional) Baixe referências adicionais e gere o índice do RAG:
   ```bash
   python teletriagem/tools/download_and_organize_refs.py --json teletriagem/kb_docs/refs.json
   python teletriagem/tools/ingest_kb.py
   ```

## Como executar

Em terminais separados:

```bash
./run_api.sh      # inicia FastAPI em http://127.0.0.1:8000
./run_ui.sh       # inicia Streamlit em http://127.0.0.1:8501
```

### Rotas principais da API

* `POST /api/triage/` — gera triagem estruturada
* `POST /api/triage/{id}/refine` — refina caso existente
* `GET /api/triage/` — lista triagens com filtros
* `POST /api/exports/pec/{id}` e `/api/exports/fhir/{id}` — exporta arquivos em `exports/`
* `GET /health` — status de execução

## Testes

Execute a suíte automatizada:

```bash
pytest teletriagem/tests
```

## RAG e Glossário

* Documentos de apoio: `teletriagem/kb_docs/refs/`
* Glossário regional: `teletriagem/kb_docs/glossario_ceara.csv`
* Índice gerado em `teletriagem/kb_docs/.index/index.json`

## Scripts utilitários

* `tools/download_and_organize_refs.py` — baixa referências descritas em `refs.json`
* `tools/ingest_kb.py` — gera índice BM25 simples
* `tools/diagnose_env.py` — imprime diagnóstico do ambiente

## Observações

* Os logs são anonimizado via redator simples (CPF/telefones).
* Temperatura padrão 0.2 para respostas conservadoras.
* Este software não substitui avaliação médica presencial.
