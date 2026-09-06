"""
Modulo test_cli.py - Pruebas Automatizadas para el CLI de Memexicanisimos Files.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestCli(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.origen = Path(self.test_dir) / "origen"
        self.destino = Path(self.test_dir) / "destino"
        self.origen.mkdir(parents=True, exist_ok=True)
        self.destino.mkdir(parents=True, exist_ok=True)

        # Crear archivos de prueba en origen
        (self.origen / "reporte.pdf").write_text("Reporte de prueba 2024")
        (self.origen / "foto.jpg").write_text("Foto simulada")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_cli_help(self):
        """Verifica que cli.py --help retorne 0 sin errores de importación."""
        cmd = [sys.executable, "cli.py", "--help"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("--origen", res.stdout)
        self.assertIn("--destino", res.stdout)
        self.assertIn("--simular", res.stdout)

    def test_cli_simular(self):
        """Verifica que la simulación por CLI no modifique archivos y retorne 0."""
        cmd = [
            sys.executable, "cli.py",
            "--origen", str(self.origen),
            "--destino", str(self.destino),
            "--simular"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("MODO SIMULACION ACTIVADO", res.stdout)
        self.assertIn("reporte.pdf", res.stdout)
        # Los archivos originales deben seguir en origen
        self.assertTrue((self.origen / "reporte.pdf").exists())

    def test_cli_ejecutar_modo_copiar(self):
        """Verifica la ejecución real en modo copiar por CLI."""
        cmd = [
            sys.executable, "cli.py",
            "--origen", str(self.origen),
            "--destino", str(self.destino),
            "--modo", "copiar"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("EJECUCION COMPLETADA", res.stdout)
        # Modo copiar preserva los originales
        self.assertTrue((self.origen / "reporte.pdf").exists())
        self.assertTrue((self.origen / "foto.jpg").exists())

    def test_cli_argumentos_faltantes(self):
        """Verifica que cli.py falle controladamente si faltan argumentos obligatorios."""
        cmd = [sys.executable, "cli.py"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("the following arguments are required: --origen, --destino", res.stderr)


if __name__ == "__main__":
    unittest.main()
