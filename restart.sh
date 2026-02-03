#!/usr/bin/bash
set -euo pipefail # Fail fast on errors

if [ "$EUID" -ne 0 ]; then
    echo "This script must be run as root."
    exit 1
fi

if [ ! -f "env_file" ]; then
    echo "'env_file' does not exist. Use env_file.example as a template."
    exit 1
fi

# The single source of truth for a clean update
docker compose up -d --build --remove-orphans