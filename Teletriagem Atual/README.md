# Teletriagem — MVP

Aplicação de triagem médica composta por um backend FastAPI e uma interface Streamlit.
O fluxo principal permite registrar triagens manuais e solicitar um resumo estruturado
gerado por um modelo via Ollama.

## Requisitos

- Python 3.12
- [Ollama](https://ollama.com/) em execução local
- Modelo `qwen3b_q4km:latest` baixado (`ollama pull qwen3b_q4km:latest`)

## Configuração

1. Crie e ative um ambiente virtual.
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

2. Instale as dependências.
   ```bash
   pip install -r requirements.txt
   ```

3. Configure as variáveis de ambiente (opcional). Caso não exista, crie um arquivo `.env`
   na raiz com o seguinte conteúdo mínimo:
   ```env
   LLM_PROVIDER=ollama
   LLM_MODEL=qwen3b_q4km:latest
   OLLAMA_BASE_URL=http://127.0.0.1:11434
   ```

## Execução

O comando abaixo inicia a API (porta `8000`) e a UI Streamlit (porta `8501`).

```bash
python run_all.py
```

Use `python run_all.py --lite` para subir apenas a API.

## Endpoints principais

- `GET /health` → status da aplicação
- `POST /api/triage/` → registra triagem manual
- `POST /api/triage/ai` → gera triagem assistida por IA (contrato fixo: `prompt`, `model_text`, `parsed`, `parse_error`, `id`)
- `GET /llm/ollama/health` → valida se o modelo configurado está disponível
- `GET /api/glossary/search` *(quando `AI_GLOSSARIO=1`)* → busca termos normalizados
- `POST /api/triage/{id}/review` *(quando `AI_HITL=1`)* → registra aceitação/override/rejeição humana
- `GET /api/triage/{id}/export/pec` *(quando `AI_EXPORT_PEC=1`)* → gera payload estruturado para PEC
- `GET /api/metrics/summary` *(quando `AI_METRICS`/`AI_DRIFT_BIAS` ativos)* → estatísticas de uso

A documentação interativa está em `http://127.0.0.1:8000/docs`.

## Interface Streamlit

A interface está em `http://127.0.0.1:8501` e oferece:

- formulário compartilhado para triagens manuais e IA;
- abas “Estruturado”, “Texto do modelo” e “JSON bruto” para cada resposta da IA, com métricas de confiança, explicações e CID-10 quando `AI_XAI`/`AI_STRICT_JSON` estiverem ativos;
- painel de debug opcional exibindo o payload enviado e a resposta recebida;
- campo na barra lateral para alterar a URL da API, consultar glossário popular (quando ativo) e visualizar métricas.
- modo HITL opcional adiciona botões para aceitar/override/rejeitar a triagem diretamente da UI.
- área “🔄 Refinar triagem” abaixo da resposta da IA para enviar complementos (gera nova versão + audit trail).
- exibição de anexos, normalizações populares, contexto epidemiológico e histórico de versões quando disponíveis.
- painel epidemiológico simplificado (necessita `AI_METRICS=1`) com agregados semanais por queixa/município.

## Feature flags (variáveis opcionais)

Todas as novas funcionalidades são **opt-in**. Defina as variáveis abaixo como `1`/`true` para ativá-las:

| Flag | Descrição |
| --- | --- |
| `AI_STRICT_JSON` | Exige JSON estrito (schema fornecido) e tenta reparo automático. Se falhar, responde `422`. |
| `AI_XAI` | Solicita explicações objetivas, perguntas de follow-up e flags de incerteza. |
| `AI_HITL` | Ativa revisão humana (Human-in-the-loop) com endpoint de decisão. |
| `AI_GLOSSARIO` | Normaliza termos populares (inclui `AI_GLOSSARIO_FILE` para carregar JSON/XLSX customizado). |
| `AI_EXPORT_PEC` | Disponibiliza exportação JSON compatível com PEC/LEDI. |
| `AI_METRICS` | Coleta métricas operacionais (latência, distribuição de prioridade, overrides). |
| `AI_DRIFT_BIAS` | Estende as métricas com checagens simples de drift/vieses. |
| `AI_DOUBLE_CHECK_ENABLED` | Executa um segundo passe do LLM para revisar omissões e corrigir o JSON. |
| `AI_CONFIDENCE_ENABLED` | Calcula pontuações de confiança por campo e geral. |
| `AI_EPI_WEIGHTING_ENABLED` | Ajusta ranking de causas prováveis usando sinais epidemiológicos simples (região/estação). |
| `AI_MIN_CONFIDENCE` | Limiar (0–1) para disparar `fallback_notice` quando a confiança geral ficar abaixo do valor. |
| `AI_LATENCY_WARN_MS` | Latência máxima tolerada em ms antes de sinalizar `latency_warning` na resposta. |

Exemplo `.env` com as flags principais:

```env
AI_STRICT_JSON=1
AI_XAI=1
AI_GLOSSARIO=1
AI_HITL=1
AI_EXPORT_PEC=1
AI_METRICS=1
AI_DOUBLE_CHECK_ENABLED=1
AI_CONFIDENCE_ENABLED=1
AI_EPI_WEIGHTING_ENABLED=1
AI_MIN_CONFIDENCE=0.7
AI_LATENCY_WARN_MS=5000
```

Para carregar um glossário customizado defina `AI_GLOSSARIO_FILE=/caminho/para/glossario.xlsx` (ou `.json`).

## Testes rápidos

Scripts de verificação manual estão em `scripts/test_api.ps1`:

```powershell
./scripts/test_api.ps1
```

O script realiza chamadas para `/health`, `/api/triage/` e `/api/triage/ai` usando PowerShell.

Para a suíte automatizada (incluindo casos críticos de triagem, refinamento e validação estrita) utilize:

```bash
pytest -q
```

## Troubleshooting

- **Modelo indisponível**: verifique `python run_all.py` e a rota `/llm/ollama/health`.
- **Portas em uso**: altere `API_PORT` ou `UI_PORT` via variáveis de ambiente.
- **Timeouts do LLM**: ajuste `LLM_CONNECT_TIMEOUT_S`, `LLM_READ_TIMEOUT_S`, etc., no `.env`.

## Deploy leve

Para uso em VPS local, recomenda-se:

- executar `uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --workers 1`;
- iniciar o Streamlit com `streamlit run ui/home.py --server.port 8501 --server.headless true`;
- manter Ollama ativo com o modelo `qwen3b_q4km:latest` previamente baixado.
