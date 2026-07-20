#!/usr/bin/env bash
set -euo pipefail

# This removes only the two named generated files before a fresh run.
product_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="$product_dir/evaluation-output"
database="$output_dir/evaluation-v1.sqlite3"
report="$output_dir/report-v1.json"

mkdir -p "$output_dir"
rm -f "$database" "$report"
export CAREER_CODESK_EVALUATION_SQLITE_PATH="$database"
export DJANGO_SETTINGS_MODULE=career_codesk.settings
export PYTHONHASHSEED=0
export TZ=UTC
export UV_CACHE_DIR="${CAREER_CODESK_UV_CACHE_DIR:-${TMPDIR:-/tmp}/career-codesk-uv-cache}"

cd "$product_dir"
mkdir -p "$UV_CACHE_DIR"
uv sync --project . --all-groups --locked
uv run --locked --no-sync python manage.py migrate --noinput
uv run --locked --no-sync python -c '
import os
import socket

def deny_network(*args, **kwargs):
    raise AssertionError("evaluation runtime must not use the network")

base_socket = socket.socket
class DeniedSocket(base_socket):
    def connect(self, *args, **kwargs):
        deny_network(*args, **kwargs)
    def connect_ex(self, *args, **kwargs):
        deny_network(*args, **kwargs)

socket.create_connection = deny_network
socket.socket = DeniedSocket

import django
django.setup()
from django.core.management import call_command
call_command("evaluate_demo", "--all", "--output", os.path.join("evaluation-output", "report-v1.json"))
'
