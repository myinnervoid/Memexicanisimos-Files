#!/usr/bin/env python3
"""
mcp/server.py - Servidor MCP Canónico para Memexicanisimos Files.

Implementa los dos transportes del protocolo MCP:
1. stdio: Comunicación mediante JSON-RPC sobre stdin/stdout para agentes locales (Claude Desktop, Cursor, Antigravity).
2. http: Endpoint HTTP/SSE en 127.0.0.1 con autenticación por token Bearer para agentes en red y nodos de n8n.

Tools expuestas:
- memex_clonar: Clonación 1:1 asíncrona O(1) en RAM con ledger y checkpointing (retorna job_id inmediato).
- memex_respaldo: Respaldo inteligente asíncrono omitiendo basura y temporales.
- memex_status: Inspección en vivo no bloqueante del estado del job y métricas de ledger.
- memex_cancel: Cancelación síncrona limpia (in-process y archivo) con liberación atómica del lock.
- memex_resume: Reanudación de jobs interrumpidos heredando parámetros y parent_job_id.
- memex_jobs_list: Listado global de trabajos históricos.
- memex_verify: Verificación de integridad en tres niveles ('ledger', 'muestra', 'full').
- memex_borrar_seguro: Eliminación protegida en sandbox estricto de servidor.
"""

import sys
import os
import json
import time
import signal
import threading
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

# Agregar directorio raíz al sys.path para importar core y services
RAIZ_APP = Path(__file__).resolve().parent.parent
if str(RAIZ_APP) not in sys.path:
    sys.path.insert(0, str(RAIZ_APP))

from logger import app_logger
from services.memex_config import MemexConfig
from services.memex_service import MemexService


class RateLimiter:
    """Limitador de tasa sliding-window en memoria aislado por cliente/token y categoría."""
    def __init__(self, max_lecturas: int = 60, max_escrituras: int = 5, ventana_s: float = 60.0):
        self.max_lecturas = max_lecturas
        self.max_escrituras = max_escrituras
        self.ventana_s = ventana_s
        self._lecturas: Dict[str, List[float]] = {}
        self._escrituras: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

    def permitir(self, tool_name: str, client_id: str = "default") -> Tuple[bool, float]:
        """Comprueba si la llamada está permitida para este client_id/token. Retorna (permitido, segundos_para_reintentar)."""
        ahora = time.monotonic()
        es_escritura = tool_name in {"memex_clonar", "memex_respaldo", "memex_borrar_seguro", "memex_resume"}
        max_ops = self.max_escrituras if es_escritura else self.max_lecturas

        with self._lock:
            cubeta = self._escrituras if es_escritura else self._lecturas
            lista = cubeta.setdefault(client_id, [])
            limite = ahora - self.ventana_s
            while lista and lista[0] < limite:
                lista.pop(0)

            if len(lista) >= max_ops:
                espera = self.ventana_s - (ahora - lista[0])
                return False, max(1.0, round(espera, 1))

            lista.append(ahora)
            return True, 0.0


TOOLS_METADATA = [
    {
        "name": "memex_clonar",
        "description": "Inicia la clonación de un directorio hacia otro por streaming O(1) en background. Retorna job_id de inmediato.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "origen": {"type": "string", "description": "Ruta absoluta de origen."},
                "destino": {"type": "string", "description": "Ruta absoluta de destino."},
                "durabilidad": {"type": "string", "enum": ["lote", "archivo", "none"], "default": "lote"},
                "incremental": {"type": "boolean", "default": True},
                "simular": {"type": "boolean", "default": False},
                "checkpoint_strict": {"type": "boolean", "default": True},
                "bloquear": {"type": "boolean", "default": False, "description": "Si es True, bloquea sincrónicamente hasta finalizar."}
            },
            "required": ["origen", "destino"]
        }
    },
    {
        "name": "memex_respaldo",
        "description": "Inicia el respaldo inteligente de perfiles personales en background. Retorna job_id de inmediato.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "perfiles": {"type": "array", "items": {"type": "string"}, "description": "Nombres de perfiles a respaldar."},
                "destino": {"type": "string", "description": "Directorio destino del respaldo."},
                "durabilidad": {"type": "string", "enum": ["lote", "archivo", "none"], "default": "lote"},
                "simular": {"type": "boolean", "default": False},
                "checkpoint_strict": {"type": "boolean", "default": True},
                "bloquear": {"type": "boolean", "default": False, "description": "Si es True, bloquea sincrónicamente hasta finalizar."}
            },
            "required": ["perfiles", "destino"]
        }
    },
    {
        "name": "memex_status",
        "description": "Consulta el estado en vivo del job y métricas del ledger sin bloquear el destino.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "destino": {"type": "string", "description": "Ruta destino del trabajo."},
                "job_id": {"type": "string", "description": "ID del job opcional. Si se omite, devuelve el último job."}
            },
            "required": ["destino"]
        }
    },
    {
        "name": "memex_cancel",
        "description": "Solicita la cancelación limpia del job y espera a que el worker libere el lock de forma atómica.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "destino": {"type": "string", "description": "Ruta destino del trabajo."},
                "job_id": {"type": "string", "description": "Identificador único del job a cancelar."},
                "timeout_s": {"type": "number", "default": 30.0, "description": "Segundos máximos a esperar la detención limpia."}
            },
            "required": ["destino", "job_id"]
        }
    },
    {
        "name": "memex_resume",
        "description": "Reanuda un trabajo interrumpido o fallido recuperando sus parámetros originales y asociando un parent_job_id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Identificador del job a reanudar."},
                "destino": {"type": "string", "description": "Ruta destino del trabajo (opcional si se encuentra en índice global)."},
                "bloquear": {"type": "boolean", "default": False}
            },
            "required": ["job_id"]
        }
    },
    {
        "name": "memex_jobs_list",
        "description": "Devuelve la lista de los últimos N trabajos registrados en el sistema.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "estado": {"type": "string", "enum": ["en_progreso", "completado", "cancelado", "error", "interrumpido"], "description": "Filtrar por estado."},
                "limite": {"type": "integer", "default": 20, "description": "Cantidad máxima de trabajos a retornar."}
            }
        }
    },
    {
        "name": "memex_verify",
        "description": "Verifica la integridad de un respaldo comparando el ledger y archivos ('ledger', 'muestra', 'full').",
        "inputSchema": {
            "type": "object",
            "properties": {
                "destino": {"type": "string", "description": "Ruta del respaldo a verificar."},
                "nivel": {"type": "string", "enum": ["ledger", "muestra", "full"], "default": "ledger"}
            },
            "required": ["destino"]
        }
    },
    {
        "name": "memex_borrar_seguro",
        "description": "Elimina archivos de forma segura exclusivamente dentro del sandbox autorizado en la configuración del servidor.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "objetivo": {"type": "string", "description": "Archivo o subdirectorio a eliminar (debe residir en sandbox)."},
                "simular": {"type": "boolean", "default": False}
            },
            "required": ["objetivo"]
        }
    }
]


def ejecutar_tool(servicio: MemexService, nombre: str, args: dict) -> dict:
    """Enruta la ejecución del tool hacia la capa MemexService."""
    bloquear = args.get("bloquear", False)
    asincrono = not bloquear

    if nombre == "memex_clonar":
        return servicio.svc_clonar(
            origen=args.get("origen", ""),
            destino=args.get("destino", ""),
            durabilidad=args.get("durabilidad", "lote"),
            incremental=args.get("incremental", True),
            simular=args.get("simular", False),
            checkpoint_strict=args.get("checkpoint_strict", True),
            asincrono=asincrono
        )
    elif nombre == "memex_respaldo":
        return servicio.svc_respaldo(
            perfiles=args.get("perfiles", []),
            destino=args.get("destino", ""),
            durabilidad=args.get("durabilidad", "lote"),
            simular=args.get("simular", False),
            checkpoint_strict=args.get("checkpoint_strict", True),
            asincrono=asincrono
        )
    elif nombre == "memex_status":
        return servicio.svc_status(
            destino=args.get("destino", ""),
            job_id=args.get("job_id")
        )
    elif nombre == "memex_cancel":
        return servicio.svc_cancel(
            destino=args.get("destino", ""),
            job_id=args.get("job_id", ""),
            timeout_s=float(args.get("timeout_s", 30.0))
        )
    elif nombre == "memex_resume":
        return servicio.svc_resume(
            job_id=args.get("job_id", ""),
            destino=args.get("destino"),
            asincrono=asincrono
        )
    elif nombre == "memex_jobs_list":
        return servicio.svc_jobs_list(
            estado=args.get("estado"),
            limite=int(args.get("limite", 20))
        )
    elif nombre == "memex_verify":
        return servicio.svc_verify(
            destino=args.get("destino", ""),
            nivel=args.get("nivel", "ledger")
        )
    elif nombre == "memex_borrar_seguro":
        return servicio.svc_borrar_seguro(
            objetivo=args.get("objetivo", ""),
            simular=args.get("simular", False)
        )
    else:
        return {"success": False, "error": f"Tool '{nombre}' desconocida.", "error_code": "ERR_UNKNOWN_TOOL"}


def modo_stdio(servicio: MemexService, rate_limiter: Optional[RateLimiter] = None):
    """Transporte MCP stdio estándar sobre stdin/stdout."""
    limiter = rate_limiter or RateLimiter()

    for line in sys.stdin:
        line_str = line.strip()
        if not line_str:
            continue
        try:
            req = json.loads(line_str)
            msg_id = req.get("id")
            method = req.get("method")
            params = req.get("params", {})

            # Manejo de Notificaciones JSON-RPC 2.0 (mensajes sin "id")
            # Según la especificación, el servidor NUNCA debe responder a una notificación
            if "id" not in req or msg_id is None:
                if method == "notifications/initialized":
                    app_logger.info("Handshake MCP: notifications/initialized recibido con éxito.")
                elif method == "notifications/cancelled":
                    app_logger.info("Notificación de cancelación recibida.")
                continue

            if method == "tools/list":
                resp = {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS_METADATA}}
            elif method == "tools/call":
                t_name = params.get("name")
                t_args = params.get("arguments", {})

                # Comprobación de Rate Limit por canal local
                permitido, espera_s = limiter.permitir(t_name, client_id="stdio_local")
                if not permitido:
                    resp = {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {
                            "code": -32029,
                            "message": f"Rate limit excedido para '{t_name}'. Reintenta en {espera_s}s."
                        }
                    }
                else:
                    res = ejecutar_tool(servicio, t_name, t_args)
                    is_err = not res.get("success", False)
                    resp = {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {
                            "content": [{"type": "text", "text": json.dumps(res, indent=2, ensure_ascii=False)}],
                            "isError": is_err
                        }
                    }
            elif method == "initialize":
                resp = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "serverInfo": {"name": "memexicanisimos-files", "version": "1.1.0"},
                        "capabilities": {"tools": {}}
                    }
                }
            else:
                resp = {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Método '{method}' no soportado."}}

            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
        except Exception as e:
            err_resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Error parseando JSON-RPC: {e}"}}
            sys.stdout.write(json.dumps(err_resp) + "\n")
            sys.stdout.flush()


def modo_http(servicio: MemexService, bind: str, puerto: int, token_esperado: str, rate_limiter: Optional[RateLimiter] = None):
    """Transporte MCP HTTP/SSE con autenticación por token Bearer para red/n8n."""
    limiter = rate_limiter or RateLimiter()

    class MCPHTTPHandler(BaseHTTPRequestHandler):
        def _enviar_json(self, status: int, data: dict, headers_extra: Optional[dict] = None):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            if headers_extra:
                for k, v in headers_extra.items():
                    self.send_header(k, str(v))
            self.end_headers()
            self.wfile.write(body)

        def _verificar_auth(self) -> bool:
            auth_h = self.headers.get("Authorization", "")
            if not auth_h.startswith("Bearer "):
                return False
            token_recibido = auth_h.split("Bearer ", 1)[1].strip()
            return token_recibido == token_esperado

        def do_GET(self):
            if not self._verificar_auth():
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Bearer realm="Memexicanisimos Files MCP"')
                self.send_header("Content-Type", "application/json; charset=utf-8")
                body = json.dumps({"error": "Unauthorized: Bearer token inválido o ausente."}).encode("utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path == "/tools":
                self._enviar_json(200, {"tools": TOOLS_METADATA})
            elif self.path == "/health":
                self._enviar_json(200, {"status": "ok", "app": "Memexicanisimos Files MCP"})
            else:
                self._enviar_json(404, {"error": "Ruta no encontrada."})

        def do_POST(self):
            if not self._verificar_auth():
                self._enviar_json(401, {"error": "Unauthorized: Bearer token inválido o ausente."})
                return

            auth_h = self.headers.get("Authorization", "")
            token_cli = auth_h.split("Bearer ", 1)[1].strip() if "Bearer " in auth_h else "anon"

            if self.path == "/mcp":
                # Transporte oficial MCP JSON-RPC 2.0 sobre HTTP
                try:
                    content_len = int(self.headers.get("Content-Length", 0))
                    raw_body = self.rfile.read(content_len).decode("utf-8")
                    req = json.loads(raw_body)
                    msg_id = req.get("id")
                    method = req.get("method")
                    params = req.get("params", {})

                    if "id" not in req or msg_id is None:
                        # Notificación: procesar y retornar 204 No Content
                        if method == "notifications/initialized":
                            app_logger.info("Handshake HTTP MCP: notifications/initialized recibido.")
                        self.send_response(204)
                        self.end_headers()
                        return

                    if method == "tools/list":
                        resp = {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS_METADATA}}
                        self._enviar_json(200, resp)
                    elif method == "tools/call":
                        t_name = params.get("name")
                        t_args = params.get("arguments", {})
                        client_id = params.get("client_id", token_cli)

                        permitido, espera_s = limiter.permitir(t_name, client_id=client_id)
                        if not permitido:
                            self._enviar_json(
                                429,
                                {
                                    "jsonrpc": "2.0",
                                    "id": msg_id,
                                    "error": {"code": -32029, "message": f"Rate limit excedido para '{t_name}'. Reintenta en {espera_s}s."}
                                },
                                headers_extra={"Retry-After": int(espera_s)}
                            )
                            return

                        res = ejecutar_tool(servicio, t_name, t_args)
                        is_err = not res.get("success", False)
                        resp = {
                            "jsonrpc": "2.0",
                            "id": msg_id,
                            "result": {
                                "content": [{"type": "text", "text": json.dumps(res, indent=2, ensure_ascii=False)}],
                                "isError": is_err
                            }
                        }
                        self._enviar_json(200, resp)
                    elif method == "initialize":
                        resp = {
                            "jsonrpc": "2.0",
                            "id": msg_id,
                            "result": {
                                "protocolVersion": "2024-11-05",
                                "serverInfo": {"name": "memexicanisimos-files", "version": "1.1.0"},
                                "capabilities": {"tools": {}}
                            }
                        }
                        self._enviar_json(200, resp)
                    else:
                        resp = {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Método '{method}' no soportado."}}
                        self._enviar_json(400, resp)
                except Exception as e:
                    self._enviar_json(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Error parseando JSON-RPC: {e}"}})

            elif self.path == "/tools/call":
                # API REST simplificada para n8n y herramientas low-code
                try:
                    content_len = int(self.headers.get("Content-Length", 0))
                    raw_body = self.rfile.read(content_len).decode("utf-8")
                    req = json.loads(raw_body)
                    t_name = req.get("name")
                    t_args = req.get("arguments", {})
                    client_id = req.get("client_id", token_cli)

                    permitido, espera_s = limiter.permitir(t_name, client_id=client_id)
                    if not permitido:
                        self._enviar_json(
                            429,
                            {"error": f"Rate limit excedido para '{t_name}'.", "retry_after": espera_s},
                            headers_extra={"Retry-After": int(espera_s)}
                        )
                        return

                    res = ejecutar_tool(servicio, t_name, t_args)
                    self._enviar_json(200, res)
                except Exception as e:
                    self._enviar_json(400, {"error": f"Error procesando solicitud: {e}"})
            elif self.path == "/notify":
                # Webhook interno para recibir notificaciones de eventos (ej. desde n8n)
                try:
                    content_len = int(self.headers.get("Content-Length", 0))
                    raw_body = self.rfile.read(content_len).decode("utf-8")
                    req = json.loads(raw_body)
                    p = Path("~/.memex/notifications.jsonl").expanduser()
                    p.parent.mkdir(parents=True, exist_ok=True)
                    # Rotación simple si supera 5 MB
                    if p.exists() and p.stat().st_size > 5 * 1024 * 1024:
                        for idx in range(3, 0, -1):
                            prev = p.with_suffix(f".{idx}.jsonl")
                            siguiente = p.with_suffix(f".{idx+1}.jsonl")
                            if prev.exists():
                                prev.replace(siguiente)
                        p.replace(p.with_suffix(".1.jsonl"))
                    req["recibido_en"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    with open(p, "a", encoding="utf-8") as f:
                        f.write(json.dumps(req, ensure_ascii=False) + "\n")
                    self._enviar_json(200, {"status": "ok", "mensaje": "Notificación guardada en ~/.memex/notifications.jsonl"})
                except Exception as e:
                    self._enviar_json(400, {"error": f"Error guardando notificación: {e}"})
            else:
                self._enviar_json(404, {"error": "Endpoint no encontrado."})

        def log_message(self, format, *args):
            pass

    server = HTTPServer((bind, puerto), MCPHTTPHandler)
    print(f"🚀 Servidor MCP HTTP escuchando en http://{bind}:{puerto} (Auth Bearer requerida)", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Servidor MCP HTTP detenido limpiamente.", file=sys.stderr)
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description="Servidor MCP para Memexicanisimos Files.")
    parser.add_argument("--modo", choices=["stdio", "http"], default="stdio", help="Transporte: 'stdio' o 'http'.")
    parser.add_argument("--bind", default=None, help="IP de bind para modo HTTP.")
    parser.add_argument("--puerto", type=int, default=None, help="Puerto para modo HTTP.")
    parser.add_argument("--config", default=None, help="Ruta alternativa a mcp.json.")
    args = parser.parse_args()

    # Si estamos en modo stdio, garantizar que los logs vayan a stderr para proteger el canal JSON-RPC
    if args.modo == "stdio":
        os.environ["MEMEX_MCP_STDIO"] = "1"
        app_logger.reconfigurar_para_stdio()

    cfg_path = Path(args.config) if args.config else None
    config = MemexConfig.cargar(cfg_path)
    servicio = MemexService(config)

    # Recuperación de huérfanos al inicio
    huerfanos = servicio.job_registry.recuperar_huerfanos()
    if huerfanos:
        app_logger.info(f"Auto-sanación: {len(huerfanos)} jobs huérfanos marcados como 'interrumpido'.")

    # Manejo cooperativo de señales (SIGTERM / SIGINT)
    def _sig_handler(sig, frame):
        app_logger.info("Detención cooperativa del servidor MCP solicitada...")
        servicio.worker_manager.shutdown()
        sys.exit(0)

    try:
        signal.signal(signal.SIGTERM, _sig_handler)
        signal.signal(signal.SIGINT, _sig_handler)
    except (ValueError, AttributeError):
        pass

    rate_limiter = RateLimiter()

    if args.modo == "stdio":
        modo_stdio(servicio, rate_limiter)
    elif args.modo == "http":
        bind_ip = args.bind or config.bind
        puerto_num = args.puerto or config.puerto
        modo_http(servicio, bind_ip, puerto_num, config.token, rate_limiter)


if __name__ == "__main__":
    main()
