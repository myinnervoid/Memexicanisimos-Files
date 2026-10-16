# Ejemplos de uso

Plantillas listas para copiar y adaptar. Ninguna contiene rutas ni credenciales reales.

## MCP
- `mcp/claude_desktop_config.json` — para Claude Desktop
- `mcp/cursor_config.json` — para Cursor
- `mcp/mcp_config.example.json` — plantilla de configuración del servidor

## CLI
Scripts bash con los casos de uso más comunes.

## Python
Uso programático de la capa de servicio (`services.memex_service`).

## Antes de usar
1. Copia `mcp/mcp_config.example.json` a `~/.config/memex/mcp.json`
2. Genera un token de ≥32 caracteres: `openssl rand -hex 32`
3. Sustituye `REEMPLAZA_CON_TOKEN` por tu token
4. Ajusta `sandbox_borrado`, `perfiles_permitidos` y `destinos_permitidos`
