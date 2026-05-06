#!/usr/bin/env bash
set -euo pipefail

skip_install=0
if [[ "${1:-}" == "--skip-install" ]]; then
  skip_install=1
fi

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
app_dir="$root_dir/app"
venv_dir="$root_dir/.venv"
venv_python="$venv_dir/bin/python"

if [[ ! -x "$venv_python" ]]; then
  echo "Creating Python virtual environment in .venv ..."
  python3 -m venv "$venv_dir"
fi

if [[ "$skip_install" -eq 0 ]]; then
  echo "Installing backend dependencies ..."
  "$venv_python" -m pip install --upgrade pip
  "$venv_python" -m pip install -r "$root_dir/requirements.txt"

  echo "Installing frontend dependencies ..."
  (cd "$app_dir" && npm install)
fi

kill_process_tree() {
  local pid="${1:-}"
  if [[ -z "$pid" ]]; then
    return
  fi

  local child_pid
  while IFS= read -r child_pid; do
    if [[ -n "$child_pid" ]]; then
      kill_process_tree "$child_pid"
    fi
  done < <(pgrep -P "$pid" 2>/dev/null || true)

  kill "$pid" 2>/dev/null || true
}

cleanup() {
  if [[ -n "${backend_pid:-}" ]]; then
    kill_process_tree "$backend_pid"
  fi
  if [[ -n "${frontend_pid:-}" ]]; then
    kill_process_tree "$frontend_pid"
  fi
}
trap cleanup EXIT INT TERM

echo "Starting backend on http://127.0.0.1:8765"
(cd "$root_dir" && "$venv_python" scripts/web_app.py) &
backend_pid=$!

echo "Starting frontend on http://localhost:1420"
echo ""
echo "Web backend:  http://127.0.0.1:8765"
echo "Web frontend: http://localhost:1420"
echo ""
(cd "$app_dir" && npm run dev:web) &
frontend_pid=$!

wait "$frontend_pid"
