"""
Modulo test_core.py - Pruebas Unitarias Automatizadas para core.py.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from datetime import date

from app_types import ServiceResult
from error_codes import ErrorCode
from core import (
    obtener_archivos, generar_plan_con_estructura,
    ejecutar_plan_con_modo, deshacer_n_operaciones,
    obtener_historial_undo
)


class TestCoreBackend(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.origen = Path(self.test_dir) / "origen"
        self.destino = Path(self.test_dir) / "destino"
        self.undo_file = Path(self.test_dir) / "undo.jsonl"

        self.origen.mkdir(parents=True, exist_ok=True)
        self.destino.mkdir(parents=True, exist_ok=True)

        # Crear archivos de prueba
        (self.origen / "doc1.pdf").write_text("Contenido documento 1")
        (self.origen / "foto1.jpg").write_text("Contenido foto 1")
        (self.origen / "foto2.jpg").write_text("Contenido foto 1")  # Duplicado binario de foto1

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_obtener_archivos_exitoso(self):
        res: ServiceResult = obtener_archivos(self.origen)
        self.assertTrue(res.success)
        self.assertEqual(len(res.data), 3)

    def test_obtener_archivos_regex_invalido(self):
        res: ServiceResult = obtener_archivos(self.origen, patron_regex="[unclosed")
        self.assertFalse(res.success)
        self.assertEqual(res.error_code, ErrorCode.ERR_REGEX_INVALID)

    def test_generar_plan_y_ejecutar_modo_copiar(self):
        res_plan: ServiceResult = generar_plan_con_estructura(
            origen=self.origen, destino_base=self.destino, usar_hash_duplicados=True
        )
        self.assertTrue(res_plan.success)
        planes = res_plan.data

        # Verificar fix T1.1: Ejecución en modo Copiar
        res_ejec: ServiceResult = ejecutar_plan_con_modo(planes, modo="Copiar")
        self.assertTrue(res_ejec.success)
        self.assertEqual(res_ejec.data["exitos"], 3)

        # Verificar que el origen siga existiendo (modo copiar)
        self.assertTrue((self.origen / "doc1.pdf").exists())

    def test_undo_operaciones_atomicas(self):
        res_plan = generar_plan_con_estructura(origen=self.origen, destino_base=self.destino)
        ejecutar_plan_con_modo(res_plan.data, modo="Mover")

        res_undo = deshacer_n_operaciones(n=3)
        self.assertTrue(res_undo.success)

    def test_clonar_carpeta_con_progreso(self):
        from core import clonar_carpeta
        dest_clone = Path(self.test_dir) / "clonado"

        progresos = []
        res = clonar_carpeta(
            origen=self.origen,
            destino=dest_clone,
            incremental=True,
            callback_progreso=lambda i, tot, b_cop, b_tot, nom: progresos.append((i, tot, b_cop, b_tot, nom))
        )
        self.assertTrue(res.success)
        self.assertEqual(res.data["copiados"], 3)
        self.assertGreater(len(progresos), 0)

    def test_service_result_api_response_contract(self):
        """Valida que ServiceResult y ApiResponse cumplan con el contrato estandarizado."""
        from app_types import ApiResponse

        # Prueba de factory ok
        ok_res = ServiceResult.ok(data={"items": 5}, message="Completado")
        self.assertTrue(ok_res.success)
        self.assertEqual(ok_res.message, "Completado")
        self.assertIsNone(ok_res.error_code)

        # Prueba de factory fail
        fail_res = ApiResponse.fail(error="Acceso denegado", error_code=ErrorCode.ERR_PERMISSION_DENIED)
        self.assertFalse(fail_res.success)
        self.assertEqual(fail_res.error, "Acceso denegado")
        self.assertEqual(fail_res.message, "Acceso denegado")
        self.assertEqual(fail_res.error_code, ErrorCode.ERR_PERMISSION_DENIED.value)

        # Prueba de to_dict
        d = fail_res.to_dict()
        self.assertEqual(d["message"], "Acceso denegado")
        self.assertEqual(d["error_code"], "ERR_PERMISSION_DENIED")

    def test_ejecutar_modo_copiar_espacio_insuficiente(self):
        """Verifica que ejecutar_plan_con_modo aborte limpiamente si el disco está lleno."""
        from unittest.mock import patch
        import collections

        res_plan = generar_plan_con_estructura(origen=self.origen, destino_base=self.destino)
        self.assertTrue(res_plan.success)

        # Simular disco con solo 10 bytes libres
        Usage = collections.namedtuple('usage', 'total used free')
        with patch('shutil.disk_usage', return_value=Usage(total=1000, used=990, free=10)):
            res_ejec = ejecutar_plan_con_modo(res_plan.data, modo="Copiar")
            self.assertFalse(res_ejec.success)
            self.assertEqual(res_ejec.error_code, ErrorCode.ERR_DISK_FULL)


if __name__ == "__main__":
    unittest.main()
