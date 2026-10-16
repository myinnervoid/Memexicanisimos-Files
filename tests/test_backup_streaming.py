"""
tests/test_backup_streaming.py - Pruebas para clonación, reanudación por ledger, locks y versionado.
"""

import unittest
import tempfile
from pathlib import Path
from core.backup import clonar_carpeta, respaldo_inteligente_windows_linux
from core.locks import adquirir_lock, LockError
from core.versioning import resolver_conflicto_versionado


class TestBackupStreaming(unittest.TestCase):
    def setUp(self):
        self.temp_origen = tempfile.TemporaryDirectory()
        self.temp_destino = tempfile.TemporaryDirectory()
        self.origen = Path(self.temp_origen.name)
        self.destino = Path(self.temp_destino.name)

        # Crear archivos de prueba en origen
        for i in range(5):
            (self.origen / f"archivo_{i}.bin").write_bytes(f"contenido_{i}".encode() * 50)

    def tearDown(self):
        self.temp_origen.cleanup()
        self.temp_destino.cleanup()

    def test_clonar_carpeta_basico_y_ledger(self):
        res = clonar_carpeta(self.origen, self.destino, usar_checkpoint=True)
        self.assertTrue(res.success)
        self.assertEqual(res.data["copiados"], 5)
        self.assertEqual(res.data["errores"], 0)

        # Verificar que el ledger se haya creado en destino
        ledger_file = self.destino / ".memex" / "checkpoint.jsonl"
        self.assertTrue(ledger_file.exists())

        # Segunda ejecución: modo incremental con ledger debe omitir todo
        res2 = clonar_carpeta(self.origen, self.destino, incremental=True, usar_checkpoint=True)
        self.assertTrue(res2.success)
        self.assertEqual(res2.data["copiados"], 0)
        self.assertEqual(res2.data["omitidos"], 5)

    def test_lock_evita_concurrencia(self):
        # Bloquear el destino manualmente
        lock = adquirir_lock(self.destino)
        try:
            # Intentar clonar debe fallar con error de lock
            res = clonar_carpeta(self.origen, self.destino)
            self.assertFalse(res.success)
            self.assertEqual(res.error_code, "ERR_LOCK_HELD")
        finally:
            lock.liberar()

        # Una vez liberado, debe permitir clonar exitosamente
        res_ok = clonar_carpeta(self.origen, self.destino)
        self.assertTrue(res_ok.success)

    def test_versionado_en_conflicto(self):
        archivo_dest = self.destino / "documento.txt"
        archivo_dest.write_text("VERSION_VIEJA_12345")

        archivo_orig = self.origen / "documento.txt"
        archivo_orig.write_text("VERSION_NUEVA_67890")

        # Resolver conflicto: debe mover la versión vieja a .historial
        dest_resuelto = resolver_conflicto_versionado(archivo_orig, archivo_dest)
        self.assertEqual(dest_resuelto, archivo_dest)

        # El destino debe haber sido movido, liberando la ruta original
        self.assertFalse(archivo_dest.exists())

        # Debe existir en .historial
        hist_dir = self.destino / ".historial"
        self.assertTrue(hist_dir.exists())
        archivos_hist = list(hist_dir.glob("*_documento.txt"))
        self.assertEqual(len(archivos_hist), 1)
    def test_simular_coincide_con_ejecucion_real(self):
        # 1. Ejecución con simular=True
        res_sim = clonar_carpeta(self.origen, self.destino, simular=True, usar_checkpoint=False)
        self.assertTrue(res_sim.success)
        d_sim = res_sim.data

        # Verificar que ningún archivo se copió en disco durante la simulación
        archivos_en_destino = list(self.destino.glob("archivo_*.bin"))
        self.assertEqual(len(archivos_en_destino), 0)

        # 2. Ejecución real
        res_real = clonar_carpeta(self.origen, self.destino, simular=False, usar_checkpoint=False)
        self.assertTrue(res_real.success)
        d_real = res_real.data

        # Los valores deben coincidir exactamente
        self.assertEqual(d_sim["total"], d_real["total"])
        self.assertEqual(d_sim["bytes_copiados"], d_real["bytes_copiados"])
        self.assertEqual(d_sim["copiados"], d_real["copiados"])

    def test_rotacion_historial_max_5(self):
        archivo_dest = self.destino / "archivo_versionado.txt"
        archivo_orig = self.origen / "archivo_versionado.txt"

        # Crear 7 versiones distintas consecutivas
        for v in range(7):
            archivo_dest.write_text(f"VERSION_ANTIGUA_{v}")
            archivo_orig.write_text(f"VERSION_NUEVA_{v}")
            resolver_conflicto_versionado(archivo_orig, archivo_dest)

        hist_dir = self.destino / ".historial"
        archivos_hist = list(hist_dir.glob("*_archivo_versionado.txt"))
        # Debe rotar manteniendo estrictamente un máximo de 5
        self.assertEqual(len(archivos_hist), 5)

    def test_clonar_replica_carpetas_vacias(self):
        vacia = self.origen / "carpeta_sin_archivos"
        vacia.mkdir()

        res = clonar_carpeta(self.origen, self.destino, preservar_vacios=True, usar_checkpoint=False)
        self.assertTrue(res.success)

        dest_vacia = self.destino / "carpeta_sin_archivos"
        self.assertTrue(dest_vacia.exists())
        self.assertTrue(dest_vacia.is_dir())

    def test_reanudacion_recopia_si_archivo_borrado_aunque_este_en_ledger(self):
        # 1. Copia inicial con checkpoint ledger
        res1 = clonar_carpeta(self.origen, self.destino, usar_checkpoint=True)
        self.assertTrue(res1.success)

        # 2. Borrar un archivo del destino (simulando "archivo fantasma")
        arch_borrado = self.destino / "archivo_1.bin"
        self.assertTrue(arch_borrado.exists())
        arch_borrado.unlink()
        self.assertFalse(arch_borrado.exists())

        # 3. Reanudar clonación con el mismo ledger: debe detectar que no existe en disco y re-copiarlo
        res2 = clonar_carpeta(self.origen, self.destino, usar_checkpoint=True)
        self.assertTrue(res2.success)
        self.assertTrue(arch_borrado.exists())
        # En la segunda corrida, debe haber copiado 1 y omitido los otros 4
        self.assertEqual(res2.data["copiados"], 1)
        self.assertEqual(res2.data["omitidos"], 4)

    def test_checkpoint_strict_rechaza_errores_pendientes(self):
        from core.checkpoint import CheckpointLedger, OpRecord
        # 1. Crear un ledger con un error pendiente
        ledger = CheckpointLedger(self.destino, batch_size=1)
        ledger.registrar(OpRecord(op_id="clone:error_previo", origen="a", destino="b", size=10, mtime_ns=1, estado="error", error="fallo_disco"))
        ledger.cerrar()

        # 2. Con checkpoint_strict=True, clonar debe rechazar y no arrancar
        res_fail = clonar_carpeta(self.origen, self.destino, checkpoint_strict=True)
        self.assertFalse(res_fail.success)
        self.assertEqual(res_fail.error_code, "ERR_CHECKPOINT_HAS_ERRORS")

        # 3. Con checkpoint_strict=False, arranca normalmente
        res_ok = clonar_carpeta(self.origen, self.destino, checkpoint_strict=False)
        self.assertTrue(res_ok.success)

    def test_seguridad_destino_dentro_de_origen_bloqueado(self):
        # Intentar respaldar dentro de sí mismo o de una subcarpeta debe fallar
        sub_destino = self.origen / "subcarpeta_backup"
        res_sub = clonar_carpeta(self.origen, sub_destino)
        self.assertFalse(res_sub.success)
        self.assertEqual(res_sub.error_code, "ERR_DESTINATION_INSIDE_ORIGIN")

        # Origen idéntico a destino
        res_mismo = clonar_carpeta(self.origen, self.origen)
        self.assertFalse(res_mismo.success)
        self.assertEqual(res_mismo.error_code, "ERR_DESTINATION_INSIDE_ORIGIN")

    def test_seguridad_destino_sin_permiso_escritura(self):
        import os
        dest_ro = self.destino / "solo_lectura"
        dest_ro.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(dest_ro, 0o555)
            if hasattr(os, "geteuid") and os.geteuid() != 0:
                res = clonar_carpeta(self.origen, dest_ro)
                self.assertFalse(res.success)
                self.assertEqual(res.error_code, "ERR_PERMISSION_DENIED")
        finally:
            os.chmod(dest_ro, 0o755)


if __name__ == '__main__':
    unittest.main()



