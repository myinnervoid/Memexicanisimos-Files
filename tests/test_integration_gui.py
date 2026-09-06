"""
Modulo test_integration_gui.py - Pruebas de Integración GUI + Backend (T3.2).
"""

import tempfile
import unittest
from pathlib import Path
import tkinter as tk

from app_types import ServiceResult
from core import generar_plan_con_estructura, ejecutar_plan_con_modo
from gui_wizard import WizardApp


class TestIntegrationGUIBackend(unittest.TestCase):

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = WizardApp(self.root)

        self.test_dir = tempfile.mkdtemp()
        self.origen = Path(self.test_dir) / "origen"
        self.destino = Path(self.test_dir) / "destino"

        self.origen.mkdir(parents=True, exist_ok=True)
        self.destino.mkdir(parents=True, exist_ok=True)

        (self.origen / "test1.txt").write_text("Prueba de integracion 1")

    def tearDown(self):
        self.root.destroy()

    def test_flujo_completo_integrado(self):
        self.app.origen = str(self.origen)
        self.app.destino = str(self.destino)
        self.app.var_modo.set("Copiar")

        res_plan: ServiceResult = generar_plan_con_estructura(
            origen=self.app.origen, destino_base=self.app.destino
        )
        self.assertTrue(res_plan.success)

        self.app.planes_actuales = res_plan.data
        self.assertEqual(len(self.app.planes_actuales), 1)

        res_ejec: ServiceResult = ejecutar_plan_con_modo(
            planes=self.app.planes_actuales, modo=self.app.var_modo.get()
        )
        self.assertTrue(res_ejec.success)


if __name__ == "__main__":
    unittest.main()
