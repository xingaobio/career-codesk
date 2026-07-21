#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
product_dir="$repo_dir/product"
temp_dir="$(mktemp -d "${TMPDIR:-/tmp}/career-codesk-static.XXXXXX")"
cleanup() { rm -rf "$temp_dir"; }
trap cleanup EXIT

export PYTHONHASHSEED=0
export TZ=UTC
export DJANGO_SETTINGS_MODULE=career_codesk.settings

uv sync --project "$product_dir" --all-groups --locked
cd "$product_dir"
uv run --locked --no-sync ruff format --check .
uv run --locked --no-sync ruff check .
uv run --locked --no-sync python manage.py test tests
uv run --locked --no-sync python manage.py check
uv run --locked --no-sync python manage.py makemigrations --check --dry-run
uv run --locked --no-sync python -c 'import career_codesk.wsgi, career_codesk.asgi'
STATIC_ROOT="$temp_dir/static" uv run --locked --no-sync python manage.py collectstatic --noinput --clear
