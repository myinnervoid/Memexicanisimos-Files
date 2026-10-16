"""
tests/test_scanner.py - Pruebas para escáner iterativo y streaming de archivos.
"""

import unittest
import tempfile
from pathlib import Path
from core.scanner import iterar_archivos, contar_archivos_y_bytes


class TestScanner(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.test_dir.name)

        # Crear estructura de prueba
        (self.root / "doc1.txt").write_bytes(b"hola")
        (self.root / "foto1.jpg").write_bytes(b"imagen_123")
        (self.root / ".oculto.txt").write_bytes(b"oculto")

        sub = self.root / "subcarpeta"
        sub.mkdir()
        (sub / "doc2.txt").write_bytes(b"mundo")

        # Carpeta a ignorar
        node_mod = self.root / "node_modules"
        node_mod.mkdir()
        (node_mod / "package.json").write_bytes(b"{}")

    def tearDown(self):
        self.test_dir.cleanup()

    def test_iterar_archivos_basico(self):
        entries = list(iterar_archivos(self.root, incluir_subcarpetas=True, incluir_ocultos=False))
        nombres = [e.path.name for e in entries]
        self.assertIn("doc1.txt", nombres)
        self.assertIn("foto1.jpg", nombres)
        self.assertIn("doc2.txt", nombres)
        self.assertNotIn(".oculto.txt", nombres)

    def test_excluir_directorios(self):
        entries = list(iterar_archivos(self.root, excluir_directorios={"node_modules"}))
        nombres = [e.path.name for e in entries]
        self.assertNotIn("package.json", nombres)

    def test_contar_archivos_y_bytes(self):
        n, b = contar_archivos_y_bytes(self.root, excluir_directorios={"node_modules"}, incluir_ocultos=False)
        self.assertEqual(n, 3)
        self.assertEqual(b, 4 + 10 + 5)

    def test_iterar_directorios_incluye_vacios(self):
        from core.scanner import iterar_directorios
        vacia = self.root / "subcarpeta" / "vacia_total"
        vacia.mkdir()

        dirs = list(iterar_directorios(self.root, excluir_directorios={"node_modules"}))
        nombres = [d.name for d in dirs]
        self.assertIn("subcarpeta", nombres)
        self.assertIn("vacia_total", nombres)
        self.assertNotIn("node_modules", nombres)


if __name__ == '__main__':
    unittest.main()

