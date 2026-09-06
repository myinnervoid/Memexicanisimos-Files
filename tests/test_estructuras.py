"""
Modulo test_estructuras.py - Pruebas Unitarias Automatizadas para generacion de rutas y estructuras.
Migrado y consolidado desde probar_estructuras.py.
"""

import unittest
from pathlib import Path
from datetime import date

from core import generar_ruta_destino, obtener_categoria


class TestGenerarRutaDestino(unittest.TestCase):

    def setUp(self):
        self.destino_base = Path("/home/usuario/Organizado")
        self.archivo_pdf = Path("/tmp/origen/informe_mensual_2024.pdf")
        self.archivo_jpg = Path("/tmp/origen/vacaciones_playa.jpg")
        self.archivo_py = Path("/tmp/origen/script_procesamiento.py")
        self.fecha_test = date(2024, 7, 24)

    def test_caso_1_legacy_por_defecto(self):
        """CASO 1: Comportamiento por defecto / legacy (sin estructura)."""
        r1 = generar_ruta_destino(self.archivo_pdf, self.fecha_test, self.destino_base)
        esp1 = self.destino_base / "2024" / "07" / "informe_mensual_2024.pdf"
        self.assertEqual(r1, esp1)

    def test_caso_2_fecha_y_categoria(self):
        """CASO 2: Criterio primario 'fecha' ({YYYY}/{MES_NOMBRE}), secundario 'tipo' (categoria)."""
        est2 = {
            'criterio_primario': 'fecha',
            'formato_fecha': '{YYYY}/{MES_NOMBRE}',
            'criterio_secundario': 'tipo',
            'organizacion_tipo': 'categoria'
        }
        r2 = generar_ruta_destino(self.archivo_jpg, self.fecha_test, self.destino_base, estructura=est2)
        esp2 = self.destino_base / "2024" / "julio" / "Imagen" / "vacaciones_playa.jpg"
        self.assertEqual(r2, esp2)

    def test_caso_3_extension_y_primera_letra(self):
        """CASO 3: Criterio primario 'tipo' (extension), secundario 'nombre' (primera_letra)."""
        est3 = {
            'criterio_primario': 'tipo',
            'organizacion_tipo': 'extension',
            'criterio_secundario': 'nombre',
            'organizacion_nombre': 'primera_letra'
        }
        r3 = generar_ruta_destino(self.archivo_py, self.fecha_test, self.destino_base, estructura=est3)
        esp3 = self.destino_base / "py" / "S" / "script_procesamiento.py"
        self.assertEqual(r3, esp3)

    def test_caso_4_nombre_completo_sin_secundario(self):
        """CASO 4: Criterio primario 'nombre' (nombre_completo), secundario 'ninguno'."""
        est4 = {
            'criterio_primario': 'nombre',
            'organizacion_nombre': 'nombre_completo',
            'criterio_secundario': 'ninguno'
        }
        r4 = generar_ruta_destino(self.archivo_pdf, self.fecha_test, self.destino_base, estructura=est4)
        esp4 = self.destino_base / "informe_mensual_2024" / "informe_mensual_2024.pdf"
        self.assertEqual(r4, esp4)

    def test_caso_5_sin_fecha(self):
        """CASO 5: Criterio primario 'fecha' ({YYYY}-{MM}-{DD}), fecha=None."""
        est5 = {
            'criterio_primario': 'fecha',
            'formato_fecha': '{YYYY}-{MM}-{DD}',
            'criterio_secundario': 'tipo',
            'organizacion_tipo': 'categoria'
        }
        r5 = generar_ruta_destino(self.archivo_jpg, None, self.destino_base, estructura=est5)
        esp5 = self.destino_base / "sin_fecha" / "Imagen" / "vacaciones_playa.jpg"
        self.assertEqual(r5, esp5)

    def test_caso_6_formato_mes_abreviado(self):
        """CASO 6: Formato de fecha con MES_ABR ({YYYY}/{MES_ABR})."""
        est6 = {
            'criterio_primario': 'fecha',
            'formato_fecha': '{YYYY}/{MES_ABR}',
            'criterio_secundario': None
        }
        r6 = generar_ruta_destino(self.archivo_py, date(2024, 1, 10), self.destino_base, estructura=est6)
        esp6 = self.destino_base / "2024" / "ene" / "script_procesamiento.py"
        self.assertEqual(r6, esp6)

    def test_obtener_categoria_conocidas(self):
        """Prueba de categorización automática por extensión."""
        self.assertEqual(obtener_categoria(Path("foto.png")), "Imagen")
        self.assertEqual(obtener_categoria(Path("video.mp4")), "Video")
        self.assertEqual(obtener_categoria(Path("audio.mp3")), "Audio")
        self.assertEqual(obtener_categoria(Path("doc.pdf")), "Documentos")
        self.assertEqual(obtener_categoria(Path("comprimido.zip")), "Comprimidos")
        self.assertEqual(obtener_categoria(Path("archivo.desconocido")), "Otros")


if __name__ == "__main__":
    unittest.main()
