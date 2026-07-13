# Wikisource

This is a simple language plugin for wikitext, to support a wikisource editor project

## Database migrations

The Python backend uses Alembic for schema changes. From the repository root:

```bash
./.venv/bin/alembic upgrade head
./.venv/bin/alembic revision --autogenerate -m "describe change"
```

Set `WTBOT_DATABASE_URL` to target a database other than `sqlite:///database.db`.
