#!/usr/bin/env bash
# Borra un directorio SOLO si está dentro del sandbox configurado.
set -euo pipefail

OBJETIVO="${1:?Uso: $0 <ruta_a_borrar>}"

memex borrar-seguro --objetivo "$OBJETIVO"

# Si el objetivo está fuera del sandbox definido en ~/.config/memex/mcp.json,
# el comando falla con ERR_SECURITY_FORBIDDEN_ZONE sin borrar nada.
