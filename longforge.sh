#!/usr/bin/env sh
set -eu
CURRENT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$CURRENT_DIR"
export PYTHONPATH="$CURRENT_DIR${PYTHONPATH:+:$PYTHONPATH}"
LONGFORGE_HOST="${LONGFORGE_HOST:-127.0.0.1}"
LONGFORGE_PORT="${LONGFORGE_PORT:-8510}"

if [ -x "$CURRENT_DIR/.venv/bin/python" ]; then
  exec "$CURRENT_DIR/.venv/bin/python" -m streamlit run "$CURRENT_DIR/longforge_app.py" --server.address="$LONGFORGE_HOST" --server.port="$LONGFORGE_PORT" --browser.gatherUsageStats=False --client.toolbarMode=minimal
elif command -v uv >/dev/null 2>&1; then
  exec uv run streamlit run "$CURRENT_DIR/longforge_app.py" --server.address="$LONGFORGE_HOST" --server.port="$LONGFORGE_PORT" --browser.gatherUsageStats=False --client.toolbarMode=minimal
else
  exec streamlit run "$CURRENT_DIR/longforge_app.py" --server.address="$LONGFORGE_HOST" --server.port="$LONGFORGE_PORT" --browser.gatherUsageStats=False --client.toolbarMode=minimal
fi
