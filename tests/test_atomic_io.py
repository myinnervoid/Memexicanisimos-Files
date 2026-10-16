"""
tests/test_atomic_io.py - Pruebas unitarias para copia atómica y durabilidad.
"""

import tempfile
import unittest
from pathlib import Path

from core.atomic_io import PARTIAL_SUFFIX, copia_atomica, limpiar_partials_huerfanos


class TestAtomicIO(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.test_dir.name)

    def tearDown(self):
        self.test_dir.cleanup()

    def test_copia_atomica_exitosa(self):
        src = self.base_path / "origen.bin"
        src.write_bytes(b"CONTENIDO_DE_PRUEBA_12345" * 100)
        dst = self.base_path / "subcarpeta" / "destino.bin"

        ok, err = copia_atomica(src, dst)
        self.assertTrue(ok)
        self.assertEqual(err, "")
        self.assertTrue(dst.exists())
        self.assertEqual(dst.read_bytes(), src.read_bytes())

        # El partial temporal debe haber desaparecido
        partial = dst.with_name(dst.name + PARTIAL_SUFFIX)
        self.assertFalse(partial.exists())

        # mtime debe coincidir
        self.assertEqual(src.stat().st_mtime, dst.stat().st_mtime)

    def test_no_deja_destino_si_falla(self):
        src = self.base_path / "archivo_inexistente.bin"
        dst = self.base_path / "fallo.bin"

        ok, err = copia_atomica(src, dst)
        self.assertFalse(ok)
        self.assertFalse(dst.exists())
        self.assertFalse((self.base_path / (dst.name + PARTIAL_SUFFIX)).exists())

    def test_limpiar_partials_huerfanos(self):
        p1 = self.base_path / f"archivo1{PARTIAL_SUFFIX}"
        p2 = self.base_path / "dir" / f"archivo2{PARTIAL_SUFFIX}"
        p2.parent.mkdir(parents=True, exist_ok=True)
        p1.write_bytes(b"corrupto1")
        p2.write_bytes(b"corrupto2")

        eliminados = limpiar_partials_huerfanos(self.base_path)
        self.assertEqual(eliminados, 2)
        self.assertFalse(p1.exists())
        self.assertFalse(p2.exists())

    def test_copia_preserva_permisos(self):
        src = self.base_path / "script.sh"
        src.write_text("#!/bin/sh\necho hi\n")
        src.chmod(0o755)
        dst = self.base_path / "script_copia.sh"
        ok, err = copia_atomica(src, dst)
        self.assertTrue(ok)
        self.assertEqual(err, "")
        self.assertEqual(dst.stat().st_mode & 0o777, 0o755)

    def test_base_exception_limpia_partial_y_propaga(self):
        src = self.base_path / "origen_simulado.txt"
        src.write_text("datos")
        dst = self.base_path / "destino_interrumpido.txt"

        # Simular KeyboardInterrupt durante la copia
        from unittest.mock import patch
        with patch("core.atomic_io._copiar_stream", side_effect=KeyboardInterrupt("Ctrl+C")):
            with self.assertRaises(KeyboardInterrupt):
                copia_atomica(src, dst)

        # El .partial no debe quedar en el filesystem
        partial = dst.with_name(dst.name + PARTIAL_SUFFIX)
        self.assertFalse(partial.exists())
        self.assertFalse(dst.exists())


if __name__ == '__main__':
    unittest.main()

