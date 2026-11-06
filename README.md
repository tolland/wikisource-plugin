# Wikisource

This is a simple language plugin for wikitext, to support a wikisource editor project

## Database migrations

The FastAPI backend and Docker test stack live in the sibling `wtbot` checkout.
The Svelte viewer is in `wtbot/viewer`. To run Alembic from the backend checkout:

```bash
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "describe change"
```

Set `WTBOT_DATABASE_URL` to target a database other than `sqlite:///database.db`.
