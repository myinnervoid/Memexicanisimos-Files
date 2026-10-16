"""
tests/test_memex_service.py - Pruebas unitarias completas de la capa de servicio MemexService.
"""

import unittest
import tempfile
import json
from pathlib import Path
from services.memex_config import MemexConfig
from services.memex_service import MemexService


class TestMemexService(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)

        self.sandbox = self.base / "staging_seguro"
        self.sandbox.mkdir()

        self.zona_privada = self.base / "privada"
        self.zona_privada.mkdir()

        self.audit_log = self.base / "audit.jsonl"
        self.config = MemexConfig(
            sandbox_borrado=self.sandbox,
            perfiles_permitidos=["Documentos", "Imágenes"],
            destinos_permitidos=["/tmp/**", str(self.base) + "/**"],
            token="token_de_prueba_de_alta_entropia_1234567890",
            audit_log=self.audit_log
        )
        self.service = MemexService(self.config)
        self.service.job_registry.global_file = self.base / "jobs.jsonl"

    def tearDown(self):
        self.service.worker_manager.shutdown()
        self.temp_dir.cleanup()

    def test_borrado_seguro_rechaza_objetivo_fuera_de_sandbox(self):
        archivo_privado = self.zona_privada / "documento.pdf"
        archivo_privado.write_text("confidencial")

        # Intentar borrar el archivo fuera del sandbox pre-configurado
        res = self.service.svc_borrar_seguro(str(archivo_privado))
        self.assertFalse(res["success"])
        self.assertEqual(res["error_code"], "ERR_SECURITY_FORBIDDEN_ZONE")
        self.assertTrue(archivo_privado.exists())

        # Verificar que la auditoría registró el intento prohibido
        self.assertTrue(self.audit_log.exists())
        log_line = json.loads(self.audit_log.read_text().splitlines()[0])
        self.assertEqual(log_line["tool"], "memex_borrar_seguro")
        self.assertEqual(log_line["resultado"], "forbidden")

    def test_borrado_seguro_permite_objetivo_dentro_de_sandbox(self):
        archivo_staging = self.sandbox / "temporal.bin"
        archivo_staging.write_text("basura")

        res = self.service.svc_borrar_seguro(str(archivo_staging))
        self.assertTrue(res["success"])
        self.assertFalse(archivo_staging.exists())

    def test_clonar_y_status_y_verify(self):
        origen = self.base / "src"
        destino = self.base / "dst"
        origen.mkdir()
        destino.mkdir()

        (origen / "f1.txt").write_text("hola")
        (origen / "f2.txt").write_text("mundo")

        # 1. Clonar vía servicio (modo síncrono para verificar data directa)
        res_clone = self.service.svc_clonar(str(origen), str(destino), durabilidad="lote", asincrono=False)
        self.assertTrue(res_clone["success"])
        self.assertEqual(res_clone["data"]["copiados"], 2)

        # 2. Consultar status
        res_status = self.service.svc_status(str(destino))
        self.assertTrue(res_status["success"])
        self.assertEqual(res_status["data"]["ledger_completados"], 2)

        # 3. Verificar integridad (nivel ledger)
        res_verify = self.service.svc_verify(str(destino), nivel="ledger")
        self.assertTrue(res_verify["success"])
        self.assertTrue(res_verify["data"]["valido"])
        self.assertEqual(res_verify["data"]["archivos_verificados"], 2)

    def test_cancelacion_job(self):
        destino = self.base / "dst_cancel"
        destino.mkdir()

        # Al llamar cancel sobre un destino sin lock activo, debe responder con éxito
        res_cancel = self.service.svc_cancel(str(destino), job_id="job_prueba_123", timeout_s=1.0)
        self.assertTrue(res_cancel["success"])
        self.assertEqual(res_cancel["data"]["estado"], "cancelado_con_exito")


if __name__ == '__main__':
    unittest.main()
