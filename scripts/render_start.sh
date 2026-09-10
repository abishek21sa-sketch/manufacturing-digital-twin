#!/bin/sh
# Render's `dockerCommand` replaces the Dockerfile's CMD and is passed to the
# container as a literal argv list, not run through a shell -- so a
# `dockerCommand:` string containing &&, $(...), or export never gets
# interpreted (every earlier deploy attempt exited immediately with status
# 128 because of this). Putting the real startup sequence in its own script
# with a proper shebang sidesteps the ambiguity: render.yaml's dockerCommand
# is just this one path, with no shell syntax for Render to mis-tokenize.
set -e

export MDT_DATABASE_URL=$(printf '%s' "$MDT_DATABASE_URL" | sed 's#^postgresql://#postgresql+psycopg://#')
alembic -c alembic.ini upgrade head
exec uvicorn mdt.api.main:app --host 0.0.0.0 --port 8000 --proxy-headers
