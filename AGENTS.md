# AI Email Automation — Agent Guide

## Entrypoints

- **FastAPI backend** — `backend/main.py` (module `main:app`), NOT `backend/app/main.py`
- **Streamlit UI (alternative)** — `backend/app.py`
- **Frontend** — `frontend/src/main.tsx`, dev server: `npm run dev` (Vite 8, port 5173)

## Commands

```bash
# Backend (from backend/)
uvicorn main:app --reload --port 8000

# Frontend (from frontend/)
npm run dev

# Railway deploy (build + start via nixpacks.toml):
#   Build: pip install -r requirements.txt
#   Start: uvicorn main:app --host 0.0.0.0 --port $PORT
```

No test, lint, typecheck, or formatter commands are configured.

## Architecture

| Concern | Location |
|---|---|
| Auth (register/login) | `backend/main.py`, SQLite `users`/`senders` tables in `backend/app/database.py` |
| Email sending (SMTP 587) | `backend/app/email_service.py` |
| Email sending (SMTP 465) | `backend/app/email_ssl_service.py` |
| Email sending (Brevo API) | `backend/app/email_brevo_service.py` (hardcoded API key — security concern) |
| Excel parsing + personalization | `backend/app/excel_utils.py` (uses `{column_name}` placeholders) |
| Vector search (semantic) | `backend/app/vector_search.py` (model: `BAAI/bge-large-en-v1.5`, SQLite embeddings) |
| AI chat (OpenRouter) | `backend/app/ai_client.py` (uses `OPENROUTER_API_KEY` + `MODEL_NAME` from `.env`) |
| One-by-one manual sending | `backend/app/manual.py` |
| Bounce detection | `backend/test.py` (scans INBOX + Spam) |
| Redis caching | Optional — app works without it |
| Frontend API client | `frontend/src/api.ts` (Axios, all endpoint mappings) |
| Auth state | `frontend/src/AuthContext.tsx` (localStorage) |

## Key facts

- **Password hashing**: SHA256 (not bcrypt) in `backend/app/database.py`
- **Redis is optional**: set `REDIS_*` in `.env` to enable; app falls back to live IMAP fetch
- **sentence-transformers** downloads `BAAI/bge-large-en-v1.5` (~1.3 GB) on first vector search
- **Excel personalization**: placeholders like `{first_name}`, `{company}` etc. are replaced from spreadsheet columns
- **Deploy root**: Railway uses `backend/` as deploy root; `railway.json` healthcheck path is `/`
- **Multi-sender**: organizations manage multiple sender accounts via `/api/senders/*` endpoints. Each sender now stores its own SMTP config (host, port, TLS) — set via provider preset (SMTP2GO/SendGrid/Mailgun/Gmail/Custom) in the frontend form.
- **SMTP provider presets**: `backend/app/database.py:SMTP_PROVIDERS` maps provider names to SMTP settings. Adding a new provider is a one-line addition.
- **`.env` required**: `SMTP_*`, `IMAP_HOST`, `OPENROUTER_API_KEY`, `MODEL_NAME` — see `INSTRUCTIONS.txt`
- **`email_ssl_service.py`** handles both SSL (port 465) and STARTTLS (587/2525) — uses `settings.port` instead of hardcoded 465.

## Security notes

- `.env` (SMTP secrets, API keys) is gitignored — never commit
- Brevo API key is hardcoded in `backend/app/email_brevo_service.py` — refactor to env variable before committing
- Passwords use SHA256, not a KDF — consider upgrading
