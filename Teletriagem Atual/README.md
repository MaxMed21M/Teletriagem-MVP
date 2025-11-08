# Teletriagem Offline (v2025.11-R3)

Plataforma de teletriagem totalmente offline para equipes de Atenção Primária à Saúde (APS) brasileiras. O sistema combina regras clínicas determinísticas e um classificador local leve para entregar decisões rápidas e auditáveis em hardware modesto (Intel i5, ≤20 GB RAM, GPU opcional).

## Visão geral

* **API FastAPI** com fila não-bloqueante (`POST /api/triage` + `GET /api/triage/status/{id}`) e suporte a calibração manual.
* **Engine híbrido**: regras NEWS2/qSOFA simplificadas + IA local (timeout + fallback) com cache LRU TTL por `xxhash`.
* **Persistência** via `aiosqlite` com `journal_mode=WAL` para concorrência segura e armazenamento de calibrações.
* **UI Streamlit** com submissão via `st.form`, polling automático, exportação JSON/PDF e gatilho de benchmark.
* **Logs LGPD-friendly** usando Loguru com ofuscação de PII e métricas (latência, cache hit, fallback, tempo de IA).

```
teletriagem/
├─ app/
│  ├─ api.py        # FastAPI + polling + calibração
│  ├─ engine.py     # Orquestra normalização → regras → IA → ensemble
│  ├─ model.py      # Executor threadpool com timeout e fallback
│  ├─ rules.py      # Regras clínicas parametrizadas
│  ├─ norm.py       # Normalização textual e discretização de vitais
│  ├─ cache.py      # Cache TTL LRU (xxhash)
│  ├─ store.py      # aiosqlite + WAL + calibração
│  ├─ export.py     # Exportação offline JSON/PDF
│  ├─ log.py        # Loguru com sanitização
│  ├─ config.py     # Carregamento de .env e defaults
│  └─ ui.py         # Streamlit com polling e benchmark
├─ resources/
│  ├─ dicionario_aps.json   # Normalização regional
│  ├─ triage_rules.json     # Parâmetros de regras clínicas
│  └─ pdf_template.html     # Referência visual
├─ scripts/bench_local.py   # Benchmark concorrente (latência média/p95)
├─ tests/                   # Pytest (API, engine, regras)
├─ requirements.txt
└─ .env.example
```

## Instalação

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Opcional: edite `.env` para ajustar caminhos de modelos, timeout, TTL do cache e diretório de logs.

## Execução

### API (FastAPI)

```bash
uvicorn teletriagem.app.api:app --reload --port 8000
```

Endpoints principais:

* `POST /api/triage` → aceita payload clínico, retorna `triage_id` imediato.
* `GET /api/triage/status/{triage_id}` → polling do status (`PROCESSANDO|COMPLETO|ERRO`).
* `POST /api/triage/{triage_id}/override` → aplica calibração manual (ajusta pesos IA/regras com média móvel leve).

### Interface Streamlit

Em um terminal separado:

```bash
streamlit run teletriagem/app/ui.py
```

Recursos da UI:

* Formulário completo de triagem com validação clínica (faixas Pydantic).
* Polling automático a cada 1 s após submissão.
* Ajuste manual do nível de triagem com persistência da calibração.
* Exportação offline em JSON e PDF (ReportLab).
* Botão **Benchmark** executando `scripts/bench_local.py` e exibindo métricas.

## Benchmark local

O script gera `performance_tests.log` com latência média/p95, tempo médio da IA, cache-hit e uso do fallback.

```bash
python scripts/bench_local.py
```

Exemplo de saída:

```json
{
  "requests": 10,
  "concurrency": 10,
  "latency_avg_ms": 4200.5,
  "latency_p95_ms": 6100.3,
  "ia_latency_avg_ms": 180.7,
  "cache_hits": 4,
  "cache_hit_rate": 0.4,
  "fallbacks": 0,
  "timestamp": "2025-02-01 12:00:00"
}
```

## Testes

```bash
pytest
```

Cobertura atual:

* `tests/test_rules.py` – valida scoring e flags.
* `tests/test_engine.py` – garante ensemble + cache + calibração.
* `tests/test_api.py` – contrato dos endpoints e ciclo completo (POST→GET→override).

## Integração de modelos locais

O módulo `teletriagem/app/model.py` utiliza `run_in_executor` para não bloquear o event loop. Para conectar um modelo real:

1. Substitua `_simulate_local_model` por chamada ao servidor/offline loader desejado.
2. Garanta timeout ≤ `INFERENCE_TIMEOUT_MS`; em caso de exceção/timeout o fallback é acionado.
3. Respeite o prompt fixo e o formato de saída JSON estrito:

```json
{"classificacao":"emergencia|urgencia|observacao|rotina","flags_ia":["...","..."]}
```

## Calibração e modos de contingência

* Sistema continua útil em modo **Rules-only**: se IA falhar repetidamente, ajuste `W_IA=0` no `.env`.
* `POST /api/triage/{id}/override` armazena o feedback humano e recalibra pesos com média móvel (`CALIBRATION_ALPHA`).
* Cache TTL baseado em `CACHE_TTL_HOURS` acelera casos semelhantes mantendo determinismo (hash por texto/vitais discretizados).

## Boas práticas LGPD

* Logs em `logs/teletriagem.log` com rotação diária e compressão.
* PII ofuscada automaticamente (`<REDACTED>` / `<PII>`).
* Exportações JSON/PDF sanitizadas antes de persistência.

## Troubleshooting

* **Latência alta** → Ajuste `CACHE_MAX_ITEMS`, confirme que hardware atende requisitos e execute `scripts/bench_local.py`.
* **IA indisponível** → Verifique caminho do modelo local, tempo de carregamento e fallback configurado.
* **Banco bloqueado** → Certifique-se de executar em disco local; WAL ativo via `aiosqlite` para concorrência.

---

Teletriagem Offline prioriza simplicidade, auditabilidade e autonomia em ambientes com conectividade restrita. Ajuste os parâmetros do ensemble e do dicionário regional conforme protocolos da sua APS.
