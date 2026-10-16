"""
tests/test_rate_limiter.py - Verifica la protección contra inundación y saturación de FS/USB.
"""

import unittest
from mcp.server import RateLimiter


class TestRateLimiter(unittest.TestCase):
    def test_limite_lecturas(self):
        limiter = RateLimiter(max_lecturas=60, max_escrituras=5, ventana_s=60.0)

        # Primeras 60 lecturas deben permitirse
        for _ in range(60):
            permitido, espera = limiter.permitir("memex_status")
            self.assertTrue(permitido)
            self.assertEqual(espera, 0.0)

        # La 61 debe ser rechazada
        permitido_61, espera_61 = limiter.permitir("memex_status")
        self.assertFalse(permitido_61)
        self.assertGreater(espera_61, 0.0)

    def test_limite_escrituras(self):
        limiter = RateLimiter(max_lecturas=60, max_escrituras=5, ventana_s=60.0)

        # Primeras 5 escrituras deben permitirse
        for _ in range(5):
            permitido, espera = limiter.permitir("memex_clonar")
            self.assertTrue(permitido)

        # La 6ta escritura debe ser rechazada
        permitido_6, espera_6 = limiter.permitir("memex_clonar")
        self.assertFalse(permitido_6)
        self.assertGreater(espera_6, 0.0)


if __name__ == "__main__":
    unittest.main()
