#!/usr/bin/env bash
# Clona la sesión de usuario (dotfiles, configs) omitiendo cachés.
set -euo pipefail

DESTINO="${1:?Uso: $0 <destino>}"

memex clonar \
  --origen "$HOME" \
  --destino "$DESTINO/sesion_$(date +%Y%m%d)" \
  --durabilidad archivo
