#!/bin/bash

# macOS double-click launcher. Resolve the project directory so Finder's
# current working directory does not affect relative files and imports.
SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

PYTHON=".venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
    printf 'Opretter Python-miljø i %s/.venv ...\n' "$SCRIPT_DIR"

    BASE_PYTHON=""
    for candidate in python3.14 python3.13 python3.12 python3; do
        if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c \
            'import sys, tkinter; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
            >/dev/null 2>&1; then
            BASE_PYTHON="$candidate"
            break
        fi
    done

    if [[ -z "$BASE_PYTHON" ]]; then
        printf 'Der blev ikke fundet Python 3.10+ med Tkinter.\n' >&2
        printf 'Installer f.eks. med: brew install python-tk@3.14\n' >&2
        read -r -p 'Tryk Enter for at lukke...' _
        exit 1
    fi

    if ! "$BASE_PYTHON" -m venv .venv; then
        printf 'Kunne ikke oprette Python-miljøet.\n' >&2
        read -r -p 'Tryk Enter for at lukke...' _
        exit 1
    fi
fi

if ! "$PYTHON" -m pip install -r requirements-gherkin.txt; then
    printf 'Afhængighederne kunne ikke installeres. Kontroller internetforbindelsen.\n' >&2
    read -r -p 'Tryk Enter for at lukke...' _
    exit 1
fi

exec "$PYTHON" "$SCRIPT_DIR/gherkin_gui.py"
