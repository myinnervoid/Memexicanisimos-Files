#!/usr/bin/env python3
"""
Script de prueba automatizado para validar la función generar_ruta_destino en core.py
con múltiples combinaciones de estructuras organizativas.
"""

import sys
from pathlib import Path
from datetime import date
from core import generar_ruta_destino, obtener_categoria


def probar_estructuras():
    print("=" * 80)
    print("INICIANDO VERIFICACIÓN DE GENERAR_RUTA_DESTINO CON DIVERSAS ESTRUCTURAS")
    print("=" * 80)

    destino_base = Path("/home/usuario/Organizado")
    archivo_pdf = Path("/tmp/origen/informe_mensual_2024.pdf")
    archivo_jpg = Path("/tmp/origen/vacaciones_playa.jpg")
    archivo_py = Path("/tmp/origen/script_procesamiento.py")

    fecha_test = date(2024, 7, 24)

    # ---------------------------------------------------------
    # CASO 1: Comportamiento por defecto / legacy (sin estructura)
    # ---------------------------------------------------------
    r1 = generar_ruta_destino(archivo_pdf, fecha_test, destino_base)
    esp1 = destino_base / "2024" / "07" / "informe_mensual_2024.pdf"
    print("\n[CASO 1 - Legacy por defecto]")
    print("  Calculado:", r1)
    print("  Esperado :", esp1)
    assert r1 == esp1, f"Falló CASO 1: {r1} != {esp1}"

    # ---------------------------------------------------------
    # CASO 2: Criterio primario 'fecha' ({YYYY}/{MES_NOMBRE}), secundario 'tipo' (categoria)
    # ---------------------------------------------------------
    est2 = {
        'criterio_primario': 'fecha',
        'formato_fecha': '{YYYY}/{MES_NOMBRE}',
        'criterio_secundario': 'tipo',
        'organizacion_tipo': 'categoria'
    }
    r2 = generar_ruta_destino(archivo_jpg, fecha_test, destino_base, estructura=est2)
    esp2 = destino_base / "2024" / "julio" / "Imagen" / "vacaciones_playa.jpg"
    print("\n[CASO 2 - Fecha {YYYY}/{MES_NOMBRE} -> Categoría]")
    print("  Calculado:", r2)
    print("  Esperado :", esp2)
    assert r2 == esp2, f"Falló CASO 2: {r2} != {esp2}"

    # ---------------------------------------------------------
    # CASO 3: Criterio primario 'tipo' (extension), secundario 'nombre' (primera_letra)
    # ---------------------------------------------------------
    est3 = {
        'criterio_primario': 'tipo',
        'organizacion_tipo': 'extension',
        'criterio_secundario': 'nombre',
        'organizacion_nombre': 'primera_letra'
    }
    r3 = generar_ruta_destino(archivo_py, fecha_test, destino_base, estructura=est3)
    esp3 = destino_base / "py" / "S" / "script_procesamiento.py"
    print("\n[CASO 3 - Tipo Extensión -> Nombre Primera Letra]")
    print("  Calculado:", r3)
    print("  Esperado :", esp3)
    assert r3 == esp3, f"Falló CASO 3: {r3} != {esp3}"

    # ---------------------------------------------------------
    # CASO 4: Criterio primario 'nombre' (nombre_completo), secundario 'ninguno'
    # ---------------------------------------------------------
    est4 = {
        'criterio_primario': 'nombre',
        'organizacion_nombre': 'nombre_completo',
        'criterio_secundario': 'ninguno'
    }
    r4 = generar_ruta_destino(archivo_pdf, fecha_test, destino_base, estructura=est4)
    esp4 = destino_base / "informe_mensual_2024" / "informe_mensual_2024.pdf"
    print("\n[CASO 4 - Nombre Completo -> Ninguno]")
    print("  Calculado:", r4)
    print("  Esperado :", esp4)
    assert r4 == esp4, f"Falló CASO 4: {r4} != {esp4}"

    # ---------------------------------------------------------
    # CASO 5: Criterio primario 'fecha' ({YYYY}-{MM}-{DD}), fecha=None
    # ---------------------------------------------------------
    est5 = {
        'criterio_primario': 'fecha',
        'formato_fecha': '{YYYY}-{MM}-{DD}',
        'criterio_secundario': 'tipo',
        'organizacion_tipo': 'categoria'
    }
    r5 = generar_ruta_destino(archivo_jpg, None, destino_base, estructura=est5)
    esp5 = destino_base / "sin_fecha" / "Imagen" / "vacaciones_playa.jpg"
    print("\n[CASO 5 - Fecha sin fecha -> Categoría]")
    print("  Calculado:", r5)
    print("  Esperado :", esp5)
    assert r5 == esp5, f"Falló CASO 5: {r5} != {esp5}"

    # ---------------------------------------------------------
    # CASO 6: Formato de fecha con MES_ABR ({YYYY}/{MES_ABR})
    # ---------------------------------------------------------
    est6 = {
        'criterio_primario': 'fecha',
        'formato_fecha': '{YYYY}/{MES_ABR}',
        'criterio_secundario': None
    }
    r6 = generar_ruta_destino(archivo_py, date(2024, 1, 10), destino_base, estructura=est6)
    esp6 = destino_base / "2024" / "ene" / "script_procesamiento.py"
    print("\n[CASO 6 - Fecha {YYYY}/{MES_ABR}]")
    print("  Calculado:", r6)
    print("  Esperado :", esp6)
    assert r6 == esp6, f"Falló CASO 6: {r6} != {esp6}"

    print("\n" + "=" * 80)
    print("✅ TODAS LAS PRUEBAS DE ESTRUCTURAS EN GENERAR_RUTA_DESTINO PASARON CON ÉXITO")
    print("=" * 80)


if __name__ == "__main__":
    probar_estructuras()
