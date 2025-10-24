# Teletriagem

Aplicação de teletriagem composta por um backend FastAPI e um frontend Streamlit. O
objetivo é registrar triagens manuais e também gerar sugestões assistidas por um
LLM servido via [Ollama](https://ollama.com/).

## Pré-requisitos

- Python 3.11+
- Ollama instalado localmente com o modelo configurado (ex.: `qwen3b_q4km`).
- `sqlite3` acessível (o projeto usa um arquivo `teletriagem.db` na raiz).

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

3. (Opcional) Copie `.env.example` para `.env` e personalize. Caso o arquivo não
   exista, configure as variáveis de ambiente diretamente. As principais são:

   | Variável | Descrição | Valor padrão |
   | --- | --- | --- |
   | `APP_NAME` | Nome exibido no FastAPI | `Teletriagem` |
   | `DATABASE_URL` | Caminho do SQLite | `sqlite+aiosqlite:///teletriagem.db` |
   | `OLLAMA_URL` | Endpoint do Ollama | `http://127.0.0.1:11434` |
   | `OLLAMA_MODEL` | Nome/alias do modelo | `qwen3b_q4km` |
   | `MAX_TOKENS` | Limite de tokens gerados | `512` |
   | `TELETRIAGEM_API_BASE` | Base URL consumida pelo Streamlit | `http://127.0.0.1:8000` |

## Execução

Abra dois terminais (ambos com o virtualenv ativo):

### Backend (FastAPI)

```bash
uvicorn backend.app.main:app --reload
```

A API ficará disponível em `http://127.0.0.1:8000`. A rota `/docs` expõe a UI do
Swagger. Durante o startup a tabela `triage_sessions` é criada/atualizada.

### Frontend (Streamlit)

```bash
streamlit run frontend/home.py
```

Caso o backend rode em host/porta diferentes, defina `TELETRIAGEM_API_BASE` ou
adicione `api_base_url` em `frontend/.streamlit/secrets.toml` ou `st.secrets`.

## Fluxos disponíveis

- **Triagem manual**: formulário padrão grava os dados em `teletriagem.db`.
- **Triagem IA**: envia os mesmos campos para o backend que consulta o LLM via
  Ollama, valida a resposta JSON e armazena tanto a estrutura normalizada quanto
  o texto bruto e a latência da chamada.
- **Histórico**: lista paginada (com cache de 30s) permitindo filtrar por origem
  (`manual` ou `ai`).

## Testes rápidos

O projeto não possui suite de testes automatizados ainda, mas você pode executar
uma checagem rápida de sintaxe:

```bash
python -m compileall backend frontend
```

## Estilo de código

- Backend prioriza async/await com `aiosqlite`.
- Preferência por validação via Pydantic (`schemas.py`).
- O frontend usa Streamlit, então widgets compartilham estado via `session_state`.

Contribuições são bem-vindas! Abra um PR descrevendo claramente o fluxo alterado
ou corrigido.
