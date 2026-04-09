#!/usr/bin/env bash
# Grocery Assistant local setup script.
# Run this once from the repo root to make the package importable.
# No internet connection or real API credentials required.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"
PY_VERSION=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")

echo "Python: $($PYTHON --version)"
echo "Repo  : $REPO_ROOT"
echo ""

# ---------------------------------------------------------------------------
# Step 1: Register the package so python -m grocery_assistant.* works
# ---------------------------------------------------------------------------

if $PYTHON -c "import grocery_assistant" 2>/dev/null; then
    echo "[ok] grocery_assistant is already importable."
else
    # Try pip editable install first
    if $PYTHON -m pip install -e "$REPO_ROOT" --quiet 2>/dev/null; then
        echo "[ok] Installed via pip editable install."
    else
        # Fall back to .pth file (works without pip)
        SITE_PACKAGES=$($PYTHON -c "import site; print(site.getusersitepackages())")
        mkdir -p "$SITE_PACKAGES"
        PTH_FILE="$SITE_PACKAGES/grocery-assistant.pth"
        echo "$REPO_ROOT/src" > "$PTH_FILE"
        echo "[ok] Registered via .pth file: $PTH_FILE"
    fi
fi

# ---------------------------------------------------------------------------
# Step 2: Verify Flask is available
# ---------------------------------------------------------------------------

if $PYTHON -c "import flask" 2>/dev/null; then
    echo "[ok] Flask is available."
else
    echo ""
    echo "[!] Flask not found. Install it with one of:"
    echo "    sudo apt-get install python3-flask"
    echo "    pip install flask"
    exit 1
fi

# ---------------------------------------------------------------------------
# Step 3: Initialize the database if it doesn't exist
# ---------------------------------------------------------------------------

DB_PATH="${GROCERY_DB_PATH:-$REPO_ROOT/grocery.db}"
if [ -f "$DB_PATH" ]; then
    echo "[ok] Database exists: $DB_PATH"
else
    $PYTHON - <<PYEOF
import sqlite3
from pathlib import Path
schema = Path("$REPO_ROOT/schema.sql").read_text()
conn = sqlite3.connect("$DB_PATH")
conn.executescript(schema)
conn.close()
print("[ok] Initialized database: $DB_PATH")
PYEOF
fi

# ---------------------------------------------------------------------------
# Step 4: Verify the CLI works
# ---------------------------------------------------------------------------

if $PYTHON -m grocery_assistant.cli --help >/dev/null 2>&1; then
    echo "[ok] CLI is working."
else
    echo "[!] CLI check failed. Something is wrong with the setup."
    exit 1
fi

echo ""
echo "Setup complete. Quick start:"
echo ""
echo "  # Show the grocery list"
echo "  python3 -m grocery_assistant.cli list"
echo ""
echo "  # Start the local web server (for SMS/Discord simulation)"
echo "  python3 -m grocery_assistant.web"
echo ""
echo "  # Run tests"
echo "  python3 -m pytest tests/ -v"
