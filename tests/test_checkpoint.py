"""
tests/test_checkpoint.py - Pruebas para CheckpointLedger y op_id determinista.
"""

import tempfile
import unittest
from pathlib import Path

from core.checkpoint import CheckpointLedger, generar_op_id


class TestCheckpoint(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.dest_root = Path(self.test_dir.name)

    def tearDown(self):
        self.test_dir.cleanup()

    def test_generar_op_id_determinista(self):
        id1 = generar_op_id("fotos/vacaciones.jpg", 1024, 1728000000000000)
        id2 = generar_op_id("fotos/vacaciones.jpg", 1024, 1728000000000000)
        id3 = generar_op_id("fotos/vacaciones.jpg", 2048, 1728000000000000)
        self.assertEqual(id1, id2)
        self.assertNotEqual(id1, id3)

    def test_ledger_registro_y_persistencia(self):
        ledger1 = CheckpointLedger(self.dest_root, batch_size=2)
        op1 = generar_op_id("doc1.pdf", 500, 1000)
        op2 = generar_op_id("doc2.pdf", 600, 1000)

        self.assertFalse(ledger1.esta_completado(op1))
        ledger1.registrar_completado(op1, "/src/doc1.pdf", "/dst/doc1.pdf", 500, 1000)
        self.assertTrue(ledger1.esta_completado(op1))

        # Al registrar el segundo, supera batch_size=2 y hace flush automático
        ledger1.registrar_completado(op2, "/src/doc2.pdf", "/dst/doc2.pdf", 600, 1000)
        ledger1.cerrar()

        ledger2 = CheckpointLedger(self.dest_root)
        self.assertEqual(ledger2.total_completados, 2)
        self.assertTrue(ledger2.esta_completado(op1))
        self.assertTrue(ledger2.esta_completado(op2))

    def test_checkpoint_tiene_errores_pendientes_y_resolucion(self):
        from core.checkpoint import OpRecord
        ledger = CheckpointLedger(self.dest_root, batch_size=1)
        op_err = "clone:error_test_1"
        op_ok = "clone:ok_test_2"

        # 1. Registrar un error
        ledger.registrar(OpRecord(op_id=op_err, origen="a", destino="b", size=10, mtime_ns=1, estado="error", error="perm_denied"))
        ledger.registrar(OpRecord(op_id=op_ok, origen="c", destino="d", size=20, mtime_ns=2, estado="completado"))
        ledger.cerrar()

        # Debe reportar 1 error pendiente
        ledger_chk = CheckpointLedger(self.dest_root)
        errores = ledger_chk.tiene_errores_pendientes()
        self.assertEqual(len(errores), 1)
        self.assertEqual(errores[0]["op_id"], op_err)

        # 2. Reintentar con éxito: registrar completado para el mismo op_id
        ledger_chk.registrar(OpRecord(op_id=op_err, origen="a", destino="b", size=10, mtime_ns=1, estado="completado"))
        ledger_chk.cerrar()

        # Ahora no debe haber errores pendientes
        ledger_final = CheckpointLedger(self.dest_root)
        self.assertEqual(len(ledger_final.tiene_errores_pendientes()), 0)

    def test_compactacion_ledger(self):
        from core.checkpoint import OpRecord
        ledger = CheckpointLedger(self.dest_root, batch_size=1)
        # Registrar múltiples transacciones sobre el mismo op_id
        ledger.registrar(OpRecord(op_id="op_x", origen="a", destino="b", size=10, mtime_ns=1, estado="copiando"))
        ledger.registrar(OpRecord(op_id="op_x", origen="a", destino="b", size=10, mtime_ns=1, estado="error", error="timeout"))
        ledger.registrar(OpRecord(op_id="op_x", origen="a", destino="b", size=10, mtime_ns=1, estado="completado"))
        ledger.cerrar()

        # Forzar compactación con umbral 0
        compactado = ledger.compactar_si_necesario(umbral_bytes=0)
        self.assertTrue(compactado)

        # El ledger ahora solo debe tener 1 línea ("completado")
        lineas = [l for l in ledger.archivo_ledger.read_text().splitlines() if l.strip()]
        self.assertEqual(len(lineas), 1)
        self.assertIn('"estado": "completado"', lineas[0])


if __name__ == '__main__':
    unittest.main()

