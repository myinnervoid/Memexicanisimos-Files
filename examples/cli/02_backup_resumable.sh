#!/usr/bin/env bash
# Respaldo reanudable. Si el proceso se interrumpe, la próxima ejecución
# omite los archivos ya completados.
set -euo pipefail

ORIGEN="${1:?Uso: $0 <origen> <destino>}"
DESTINO="${2:?Uso: $0 <origen> <destino>}"

memex clonar \
  --origen "$ORIGEN" \
  --destino "$DESTINO" \
  --incremental \
  --reanudar \
  --durabilidad lote
