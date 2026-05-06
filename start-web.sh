#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$root_dir/scripts/start_web_dev.sh" "$@"
