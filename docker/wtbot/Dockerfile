FROM python:3.13-slim

# Dependencies are installed from pyproject.toml, deliberately *not* from
# uv.lock: the lock file is not committed because this project builds against a
# LAN pypi mirror and the lock would carry LAN-local URLs (see CLAUDE.md).
COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /usr/local/bin/uv

WORKDIR /app

# Deps first, so editing source does not reinstall pywikibot.
COPY pyproject.toml ./
RUN uv pip install --system --no-cache -r pyproject.toml

# alembic.ini sits at the project root, which is what wtbot.db.alembic_config
# resolves from the package location (PACKAGE_ROOT.parents[1]).
COPY alembic.ini ./
COPY src-py/wtbot ./src-py/wtbot
COPY docker/wtbot/start-wtbot.sh /usr/local/bin/start-wtbot
RUN chmod +x /usr/local/bin/start-wtbot

# Run from source on PYTHONPATH rather than installing the package: it is the
# same import layout the tests and the CLI use locally (pythonpath = src-py),
# so a container cannot diverge from what everyone else runs.
ENV PYTHONPATH=/app/src-py \
    WTBOT_DATABASE_URL=sqlite:////data/wtbot.db \
    WTBOT_BLOB_ROOT=/data/blobs \
    WTBOT_PORT=8000

EXPOSE 8000

CMD ["start-wtbot"]
