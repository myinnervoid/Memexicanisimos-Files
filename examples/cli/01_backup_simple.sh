#!/usr/bin/env bash
# Respaldo simple de Documentos a un disco externo.
set -euo pipefail

ORIGEN="$HOME/Documentos"
DESTINO="/media/$USER/DiscoExterno/Backup_Documentos"

memex respaldo \
  --origen "$ORIGEN" \
  --destino "$DESTINO" \
  --incremental \
  --durabilidad lote
