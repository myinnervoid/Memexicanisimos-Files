"""
tests/test_security.py - Pruebas para el guardián de borrado seguro y sandbox.
"""

import tempfile
import unittest
from pathlib import Path

from core.security import SecuritySandboxError, borrar_seguro, validar_dentro_de_sandbox


class TestSecuritySandbox(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)

        self.area_sandbox = self.base / "zona_cuarentena"
        self.area_sandbox.mkdir()

        self.fuera_sandbox = self.base / "zona_privada"
        self.fuera_sandbox.mkdir()

        (self.area_sandbox / "basura.txt").write_text("eliminar_esto")
        (self.fuera_sandbox / "secreto.txt").write_text("no_tocar")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_borrado_permitido_dentro_de_sandbox(self):
        obj = self.area_sandbox / "basura.txt"
        res = borrar_seguro(obj, self.area_sandbox)
        self.assertTrue(res.success)
        self.assertFalse(obj.exists())

    def test_bloqueo_fuera_de_sandbox(self):
        obj = self.fuera_sandbox / "secreto.txt"
        res = borrar_seguro(obj, self.area_sandbox)
        self.assertFalse(res.success)
        self.assertEqual(res.error_code, "ERR_SECURITY_SANDBOX_VIOLATION")
        self.assertTrue(obj.exists())

    def test_bloqueo_raiz_de_sandbox(self):
        # Intentar borrar la raíz misma del área debe ser rechazado
        res = borrar_seguro(self.area_sandbox, self.area_sandbox)
        self.assertFalse(res.success)
        self.assertEqual(res.error_code, "ERR_SECURITY_SANDBOX_VIOLATION")
        self.assertTrue(self.area_sandbox.exists())

    def test_rechazo_sandbox_critico(self):
        # Intentar definir / o /home como sandbox debe fallar
        with self.assertRaises(SecuritySandboxError):
            validar_dentro_de_sandbox(Path("/home/usuario/doc.txt"), Path("/home"))

    def test_symlink_hacia_afuera_no_borra_objetivo_externo(self):
        # Crear subdirectorio en sandbox con symlink apuntando a archivo confidencial fuera
        carpeta_sub = self.area_sandbox / "carpeta_con_link"
        carpeta_sub.mkdir()

        archivo_confidencial = self.fuera_sandbox / "secreto.txt"
        symlink_peligroso = carpeta_sub / "enlace_al_secreto.txt"
        symlink_peligroso.symlink_to(archivo_confidencial)

        # Borrar el subdirectorio dentro del sandbox
        res = borrar_seguro(carpeta_sub, self.area_sandbox)
        self.assertTrue(res.success)

        # El subdirectorio y el symlink deben estar eliminados
        self.assertFalse(carpeta_sub.exists())
        self.assertFalse(symlink_peligroso.exists())

        # CRÍTICO: El archivo objetivo fuera del sandbox DEBE seguir intacto
        self.assertTrue(archivo_confidencial.exists())
        self.assertEqual(archivo_confidencial.read_text(), "no_tocar")

    def test_objetivo_symlink_fuera_del_sandbox_rechazado(self):
        # Si el usuario o agente pasa directamente como objetivo un symlink
        # que reside dentro del sandbox pero cuyo destino real está afuera,
        # validar_dentro_de_sandbox lo resuelve con realpath() y lo bloquea
        # impidiendo que se toque el destino fuera de la jaula.
        symlink_directo = self.area_sandbox / "link_directo_afuera"
        archivo_confidencial = self.fuera_sandbox / "secreto.txt"
        symlink_directo.symlink_to(archivo_confidencial)

        res = borrar_seguro(symlink_directo, self.area_sandbox)
        self.assertFalse(res.success)
        self.assertEqual(res.error_code, "ERR_SECURITY_SANDBOX_VIOLATION")
        self.assertTrue(archivo_confidencial.exists())
        self.assertTrue(symlink_directo.exists())


if __name__ == '__main__':
    unittest.main()

