"""
tests/test_audit_redaction.py - Verifica que el audit log redacta rutas privadas ($HOME -> ~).
"""

import json
import tempfile
import unittest
from pathlib import Path

from services.memex_config import MemexConfig
from services.memex_service import MemexService


class TestAuditRedaction(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)

        self.audit_file = self.base / "mcp_audit.jsonl"
        self.sandbox = self.base / "staging"
        self.sandbox.mkdir()

        self.config = MemexConfig(
            sandbox_borrado=self.sandbox,
            perfiles_permitidos=["Documentos"],
            destinos_permitidos=["/tmp/**", str(self.base) + "/**"],
            token="a" * 32,
            audit_log=self.audit_file
        )
        self.service = MemexService(config=self.config)

    def tearDown(self):
        self.service.worker_manager.shutdown()
        self.temp_dir.cleanup()

    def test_audit_redacta_home_privado(self):
        home_path = Path.home()
        ruta_privada = str(home_path / "Documentos" / "secreto.txt")

        # Ejecutar una llamada pasando rutas bajo $HOME
        self.service.svc_status(destino=ruta_privada, job_id="job_dummy")

        self.assertTrue(self.audit_file.exists())
        lineas = self.audit_file.read_text(encoding="utf-8").strip().splitlines()
        self.assertGreater(len(lineas), 0)

        entrada = json.loads(lineas[-1])
        params_str = json.dumps(entrada["params"])

        # Verificar que la ruta física del usuario no aparece
        self.assertNotIn(str(home_path), params_str)
        # Verificar que fue reemplazada por tilde '~'
        self.assertIn("~/Documentos/secreto.txt", params_str)


if __name__ == "__main__":
    unittest.main()
