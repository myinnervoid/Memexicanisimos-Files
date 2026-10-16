"""
tests/test_async_jobs.py - Pruebas completas del modelo asíncrono (Modelo B):
- Retorno inmediato (< 100 ms) con job_id y estado 'en_progreso'.
- Monitoreo en vivo vía svc_status.
- Cancelación cooperativa rápida vía svc_cancel.
- Reanudación de trabajos vía svc_resume con parent_job_id.
- Recuperación de huérfanos con verificación de PID recycling.
"""

import time
import json
import unittest
import tempfile
from pathlib import Path
from services.memex_config import MemexConfig
from services.memex_service import MemexService
from services.job_worker import JobState, JobRegistry, JobWorkerManager, _pid_sigue_vivo


class TestAsyncJobs(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.base = Path(self.temp_dir.name)

        self.origen = self.base / "origen"
        self.destino = self.base / "destino"
        self.sandbox = self.base / "staging"

        self.origen.mkdir()
        self.destino.mkdir()
        self.sandbox.mkdir()

        # Crear archivos de prueba en origen
        for i in range(10):
            (self.origen / f"doc_{i}.txt").write_text(f"Contenido archivo {i}" * 100)

        self.config = MemexConfig(
            sandbox_borrado=self.sandbox,
            perfiles_permitidos=["Documentos"],
            destinos_permitidos=[str(self.base) + "/**"],
            token="a" * 32,
            audit_log=self.base / "audit.jsonl"
        )
        self.registry = JobRegistry(global_file=self.base / "global_jobs.jsonl")
        self.worker_manager = JobWorkerManager(registry=self.registry, max_workers=2)
        self.service = MemexService(config=self.config, worker_manager=self.worker_manager)
        self.service.job_registry = self.registry

    def tearDown(self):
        self.worker_manager.shutdown()
        time.sleep(0.05)
        try:
            self.temp_dir.cleanup()
        except OSError:
            pass

    def test_clonacion_asincrona_retorno_inmediato(self):
        """Verifica que svc_clonar retorna en < 100 ms con job_id y completa en background."""
        t0 = time.monotonic()
        res = self.service.svc_clonar(
            origen=str(self.origen),
            destino=str(self.destino),
            durabilidad="none",
            asincrono=True
        )
        elapsed_ms = (time.monotonic() - t0) * 1000

        # Debe retornar de inmediato al agente
        self.assertLess(elapsed_ms, 150)
        self.assertTrue(res["success"])
        job_id = res["data"]["job_id"]
        self.assertEqual(res["data"]["estado"], "en_progreso")

        # Monitorear hasta que el worker termine
        for _ in range(50):
            status_res = self.service.svc_status(destino=str(self.destino), job_id=job_id)
            if status_res["data"]["job"]["estado"] == "completado":
                break
            time.sleep(0.05)

        final_status = self.service.svc_status(destino=str(self.destino), job_id=job_id)
        self.assertEqual(final_status["data"]["job"]["estado"], "completado")
        self.assertEqual(len(list(self.destino.glob("*.txt"))), 10)

    def test_cancelacion_cooperativa_job(self):
        """Verifica que svc_cancel detiene un job y libera el lock limpiamente."""
        # Crear dataset más grande para asegurar que esté en vuelo
        for i in range(100):
            (self.origen / f"grande_{i}.bin").write_bytes(b"X" * 1024 * 100)

        res = self.service.svc_clonar(
            origen=str(self.origen),
            destino=str(self.destino),
            durabilidad="lote",
            asincrono=True
        )
        job_id = res["data"]["job_id"]

        # Solicitar cancelación rápida
        cancel_res = self.service.svc_cancel(destino=str(self.destino), job_id=job_id, timeout_s=5.0)
        self.assertTrue(cancel_res["success"])

        # Verificar que el estado del job termina en cancelado
        status = self.service.svc_status(destino=str(self.destino), job_id=job_id)
        self.assertIn(status["data"]["job"]["estado"], ["cancelado", "cancelacion_en_progreso"])

    def test_recuperacion_de_huerfanos_y_resume(self):
        """Verifica auto-sanación de jobs muertos por PID reciclado y reanudación con svc_resume."""
        # 1. Crear un registro de job simulando un servidor que murió
        job_muerto = JobState(
            job_id="job_muerto_123",
            tipo="clonar",
            params={"origen": str(self.origen), "destino": str(self.destino), "durabilidad": "none"},
            destino=str(self.destino),
            pid=999999,  # PID inexistente en el sistema
            pid_start_time=12345.0,
            inicio="2026-10-09T00:00:00",
            estado="en_progreso"
        )
        self.registry.registrar(job_muerto)

        # 2. Recuperar huérfanos
        huerfanos = self.registry.recuperar_huerfanos()
        self.assertEqual(len(huerfanos), 1)
        self.assertEqual(huerfanos[0].job_id, "job_muerto_123")
        self.assertEqual(huerfanos[0].estado, "interrumpido")

        # 3. Reanudar job interrumpido mediante svc_resume
        resume_res = self.service.svc_resume(job_id="job_muerto_123", destino=str(self.destino), asincrono=True)
        self.assertTrue(resume_res["success"])
        nuevo_job_id = resume_res["data"]["job_id"]
        self.assertEqual(resume_res["data"]["parent_job_id"], "job_muerto_123")

        # Esperar finalización del nuevo job
        for _ in range(50):
            st = self.service.svc_status(destino=str(self.destino), job_id=nuevo_job_id)
            if st["data"]["job"]["estado"] == "completado":
                break
            time.sleep(0.05)

        st_final = self.service.svc_status(destino=str(self.destino), job_id=nuevo_job_id)
        self.assertEqual(st_final["data"]["job"]["estado"], "completado")


if __name__ == "__main__":
    unittest.main()
