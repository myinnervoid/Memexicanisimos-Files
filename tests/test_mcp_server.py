"""
tests/test_mcp_server.py - Pruebas completas del servidor MCP (stdio y HTTP con autenticación Bearer).
"""

import unittest
import tempfile
import json
import threading
import urllib.request
import urllib.error
from pathlib import Path
from services.memex_config import MemexConfig
from services.memex_service import MemexService
from mcp.server import ejecutar_tool, modo_http


class TestMCPServer(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)

        self.sandbox = self.base / "staging"
        self.sandbox.mkdir()

        # Desactivar proxies de entorno para peticiones a 127.0.0.1 en pruebas
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        urllib.request.install_opener(opener)

        self.token = "token_mcp_prueba_con_mas_de_32_caracteres_123"
        self.config = MemexConfig(
            sandbox_borrado=self.sandbox,
            perfiles_permitidos=["Documentos"],
            destinos_permitidos=["/tmp/**"],
            token=self.token,
            audit_log=self.base / "audit.jsonl"
        )
        self.service = MemexService(self.config)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_ejecutar_tool_dispatch(self):
        # 1. Dispatch de tool conocido
        res_list = ejecutar_tool(self.service, "memex_jobs_list", {"limite": 5})
        self.assertTrue(res_list["success"])
        self.assertIn("jobs", res_list["data"])

        # 2. Dispatch de tool desconocido
        res_err = ejecutar_tool(self.service, "tool_inexistente", {})
        self.assertFalse(res_err["success"])
        self.assertEqual(res_err["error_code"], "ERR_UNKNOWN_TOOL")

    def test_http_auth_rechazo_y_exito(self):
        # Iniciar servidor HTTP temporal en puerto libre
        puerto = 18701
        hilo = threading.Thread(
            target=modo_http,
            args=(self.service, "127.0.0.1", puerto, self.token),
            daemon=True
        )
        hilo.start()

        import time
        time.sleep(0.2)  # Dar tiempo a arrancar

        url_health = f"http://127.0.0.1:{puerto}/health"
        url_call = f"http://127.0.0.1:{puerto}/tools/call"

        # 1. Llamada sin token Bearer debe devolver 401
        req_sin_auth = urllib.request.Request(url_health)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req_sin_auth)
        self.assertEqual(ctx.exception.code, 401)

        # 2. Llamada con token Bearer correcto debe devolver 200
        req_con_auth = urllib.request.Request(url_health, headers={"Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(req_con_auth) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode())
            self.assertEqual(data["status"], "ok")

        # 3. Llamada a tools/call con token
        payload = json.dumps({"name": "memex_jobs_list", "arguments": {"limite": 10}}).encode("utf-8")
        req_post = urllib.request.Request(
            url_call,
            data=payload,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req_post) as resp:
            self.assertEqual(resp.status, 200)
            res_json = json.loads(resp.read().decode())
            self.assertTrue(res_json["success"])

    def test_mcp_rate_limit_http(self):
        """Verifica que el servidor MCP HTTP responde 429 al exceder la tasa de escrituras."""
        from mcp.server import RateLimiter
        puerto = 18702
        limiter = RateLimiter(max_lecturas=60, max_escrituras=2, ventana_s=60.0)
        hilo = threading.Thread(
            target=modo_http,
            args=(self.service, "127.0.0.1", puerto, self.token, limiter),
            daemon=True
        )
        hilo.start()

        import time
        time.sleep(0.2)
        url_call = f"http://127.0.0.1:{puerto}/tools/call"

        # Dos escrituras permitidas
        payload = json.dumps({"name": "memex_borrar_seguro", "arguments": {"objetivo": str(self.sandbox / "inexistente"), "simular": True}}).encode("utf-8")
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

        for _ in range(2):
            req = urllib.request.Request(url_call, data=payload, headers=headers)
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.status, 200)

        # La 3ra debe devolver HTTP 429 (Too Many Requests)
        req_bloqueado = urllib.request.Request(url_call, data=payload, headers=headers)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req_bloqueado)
        # La 3ra debe devolver HTTP 429 (Too Many Requests)
        req_bloqueado = urllib.request.Request(url_call, data=payload, headers=headers)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req_bloqueado)
        self.assertEqual(ctx.exception.code, 429)

    def test_mcp_stdio_handshake_and_content_format(self):
        """Verifica que el servidor stdio maneja el handshake completo y retorna content[] válido."""
        import io
        import sys
        from mcp.server import modo_stdio

        # Simular secuencia real de cliente Claude Desktop:
        # 1. initialize
        # 2. notifications/initialized (SIN ID, no debe generar respuesta a stdout)
        # 3. tools/list
        # 4. tools/call memex_jobs_list
        entradas = [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
            json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "memex_jobs_list", "arguments": {"limite": 5}}})
        ]

        old_stdin = sys.stdin
        old_stdout = sys.stdout
        sys.stdin = io.StringIO("\n".join(entradas) + "\n")
        captura_stdout = io.StringIO()
        sys.stdout = captura_stdout

        try:
            modo_stdio(self.service)
        finally:
            sys.stdin = old_stdin
            sys.stdout = old_stdout

        lineas = [l for l in captura_stdout.getvalue().strip().split("\n") if l.strip()]

        # Deben haber exactamente 3 respuestas (la notificación NO genera respuesta)
        self.assertEqual(len(lineas), 3)

        # 1. Respuesta a initialize
        r1 = json.loads(lineas[0])
        self.assertEqual(r1["id"], 1)
        self.assertEqual(r1["result"]["protocolVersion"], "2024-11-05")

        # 2. Respuesta a tools/list
        r2 = json.loads(lineas[1])
        self.assertEqual(r2["id"], 2)
        tools = r2["result"]["tools"]
        self.assertGreater(len(tools), 0)
        self.assertIn("inputSchema", tools[0])

        # 3. Respuesta a tools/call con content[] tipado y isError
        r3 = json.loads(lineas[2])
        self.assertEqual(r3["id"], 3)
        self.assertIn("result", r3)
        self.assertIn("content", r3["result"])
        self.assertIn("isError", r3["result"])
        self.assertEqual(r3["result"]["isError"], False)
        self.assertEqual(r3["result"]["content"][0]["type"], "text")

        # Verificar que el payload dentro de content[0].text es JSON parseable
        parsed_inner = json.loads(r3["result"]["content"][0]["text"])
        self.assertTrue(parsed_inner["success"])

    def test_mcp_rate_limit_token_isolation(self):
        """Verifica que el rate limit aisla tokens: cliente A agotado no bloquea a cliente B."""
        from mcp.server import RateLimiter
        limiter = RateLimiter(max_lecturas=60, max_escrituras=2, ventana_s=60.0)

        # Cliente A consume sus 2 escrituras
        self.assertTrue(limiter.permitir("memex_clonar", client_id="token_A")[0])
        self.assertTrue(limiter.permitir("memex_clonar", client_id="token_A")[0])
        # Cliente A es bloqueado en la 3ra
        self.assertFalse(limiter.permitir("memex_clonar", client_id="token_A")[0])

        # Cliente B debe seguir teniendo cuota disponible
        self.assertTrue(limiter.permitir("memex_clonar", client_id="token_B")[0])
        self.assertTrue(limiter.permitir("memex_clonar", client_id="token_B")[0])
        self.assertFalse(limiter.permitir("memex_clonar", client_id="token_B")[0])

    def test_mcp_http_jsonrpc_endpoint(self):
        """Verifica que el endpoint POST /mcp procesa JSON-RPC 2.0 y retorna content[] conforme a spec."""
        puerto = 18703
        hilo = threading.Thread(
            target=modo_http,
            args=(self.service, "127.0.0.1", puerto, self.token),
            daemon=True
        )
        hilo.start()

        import time
        time.sleep(0.2)
        url_mcp = f"http://127.0.0.1:{puerto}/mcp"

        # 1. Enviar initialize sobre HTTP
        init_body = json.dumps({"jsonrpc": "2.0", "id": 10, "method": "initialize"}).encode("utf-8")
        req_init = urllib.request.Request(
            url_mcp,
            data=init_body,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req_init) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode())
            self.assertEqual(data["result"]["protocolVersion"], "2024-11-05")

        # 2. Enviar tools/call sobre HTTP
        call_body = json.dumps({
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {"name": "memex_jobs_list", "arguments": {"limite": 3}}
        }).encode("utf-8")
        req_call = urllib.request.Request(
            url_mcp,
            data=call_body,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req_call) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode())
            self.assertEqual(data["id"], 11)
            self.assertIn("content", data["result"])
            self.assertEqual(data["result"]["content"][0]["type"], "text")
            inner_res = json.loads(data["result"]["content"][0]["text"])
            self.assertTrue(inner_res["success"])


if __name__ == '__main__':
    unittest.main()
