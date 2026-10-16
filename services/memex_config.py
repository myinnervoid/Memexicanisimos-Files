"""
services/memex_config.py - Configuración Estricta y Blindaje del Sandbox para el Servidor MCP.

Reglas de Oro:
1. El sandbox_borrado NUNCA es parametrizable por tool call del agente.
2. Se resuelve canónicamente al inicio con strict=True.
3. Se rechazan symlinks en el sandbox y raíces críticas del sistema (/, /home, $HOME, etc.).
4. Autenticación fuerte mediante token Bearer (≥32 caracteres).
"""

import os
import json
import secrets
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional

RUTAS_PROHIBIDAS_COMO_SANDBOX = {
    Path("/").resolve(),
    Path("/root").resolve(),
    Path("/home").resolve(),
    Path("/etc").resolve(),
    Path("/usr").resolve(),
    Path("/var").resolve(),
    Path("/bin").resolve(),
    Path("/sbin").resolve(),
    Path("/boot").resolve(),
    Path("/sys").resolve(),
    Path("/proc").resolve(),
    Path.home().resolve(),
}


@dataclass(frozen=True)
class MemexConfig:
    sandbox_borrado: Path
    perfiles_permitidos: List[str]
    destinos_permitidos: List[str]
    token: str
    bind: str = "127.0.0.1"
    puerto: int = 7801
    audit_log: Path = Path("~/.memex/mcp_audit.jsonl")

    @classmethod
    def cargar(cls, config_path: Optional[Path] = None) -> "MemexConfig":
        path = config_path or Path("~/.config/memex/mcp.json").expanduser()

        # Si no existe la configuración inicial, generar plantilla segura por defecto
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            default_staging = Path("~/.memex/staging").expanduser()
            default_staging.mkdir(parents=True, exist_ok=True)
            default_token = secrets.token_hex(24)  # 48 caracteres

            default_raw = {
                "sandbox_borrado": str(default_staging),
                "perfiles_permitidos": ["Documentos", "Imágenes", "Vídeos", "Música", "Escritorio"],
                "destinos_permitidos": ["/media/**", "/mnt/**", "/tmp/**"],
                "token": default_token,
                "bind": "127.0.0.1",
                "puerto": 7801,
                "audit_log": "~/.memex/mcp_audit.jsonl"
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(default_raw, f, indent=2)

            token_file = path.parent / "mcp_token"
            token_file.write_text(default_token, encoding="utf-8")
            token_file.chmod(0o600)

        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        # 1. Validar sandbox de borrado
        raw_sandbox = Path(raw.get("sandbox_borrado", "~/.memex/staging")).expanduser()
        if raw_sandbox.is_symlink():
            raise ValueError(f"Configuración inválida: 'sandbox_borrado' no puede ser un enlace simbólico ({raw_sandbox}).")

        raw_sandbox.mkdir(parents=True, exist_ok=True)
        sandbox_real = raw_sandbox.resolve(strict=True)

        if sandbox_real in RUTAS_PROHIBIDAS_COMO_SANDBOX:
            raise ValueError(f"Configuración peligrosa: 'sandbox_borrado' apunta a un directorio prohibido del sistema ({sandbox_real}).")

        # 2. Validar token
        token = raw.get("token", "").strip()
        if len(token) < 32:
            raise ValueError(f"Configuración insegura: 'token' debe contener al menos 32 caracteres (actual: {len(token)}).")

        audit_path = Path(raw.get("audit_log", "~/.memex/mcp_audit.jsonl")).expanduser()
        audit_path.parent.mkdir(parents=True, exist_ok=True)

        return cls(
            sandbox_borrado=sandbox_real,
            perfiles_permitidos=raw.get("perfiles_permitidos", []),
            destinos_permitidos=raw.get("destinos_permitidos", []),
            token=token,
            bind=raw.get("bind", "127.0.0.1"),
            puerto=int(raw.get("puerto", 7801)),
            audit_log=audit_path,
        )
