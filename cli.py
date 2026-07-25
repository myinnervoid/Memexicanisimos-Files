#!/usr/bin/env python3
"""
Modulo cli.py - Interfaz de Linea de Comandos (CLI) para organizacion masiva de archivos.

Este script permite ejecutar la organizacion de archivos por fecha desde la terminal
ofreciendo opciones para previsualizar/simular planes o ejecutarlos directamente.
"""

import argparse
import sys
from pathlib import Path
from core import generar_plan, simular_plan, ejecutar_plan, RutaNoValidaError


def main():
    parser = argparse.ArgumentParser(
        description="Herramienta CLI para organizar archivos por fecha (Año/Mes) y gestionar duplicados de forma segura.",
        formatter_class=argparse.RawTextHelpFormatter
    )

    # Argumentos obligatorios
    parser.add_argument(
        "--origen",
        required=True,
        type=str,
        help="Ruta del directorio fuente de donde se leeran los archivos."
    )
    parser.add_argument(
        "--destino",
        required=True,
        type=str,
        help="Ruta del directorio raiz donde se creara la estructura de carpetas Año/Mes."
    )

    # Argumentos opcionales
    parser.add_argument(
        "--extensiones",
        type=str,
        default=None,
        help="Lista de extensiones separadas por comas a filtrar. Ej: '.jpg,.png,.jpeg' (Por defecto incluye todas)."
    )
    parser.add_argument(
        "--sin-subcarpetas",
        action="store_true",
        help="Si se especifica, solo analiza la carpeta nivel superior (desactiva escaneo recursivo)."
    )
    parser.add_argument(
        "--sin-exif",
        action="store_true",
        help="Si se especifica, desactiva la lectura de metadatos EXIF en imagenes."
    )
    parser.add_argument(
        "--hash",
        action="store_true",
        help="Activa la deteccion de duplicados exactos por contenido usando hash MD5."
    )
    parser.add_argument(
        "--simular",
        action="store_true",
        help="Modo de prueba: Genera y muestra la simulación del plan sin mover ningun archivo."
    )

    args = parser.parse_args()

    # Procesar lista de extensiones si fue proporcionada
    lista_extensiones = None
    if args.extensiones:
        lista_extensiones = [ext.strip() for ext in args.extensiones.split(",") if ext.strip()]

    ruta_origen = Path(args.origen)
    ruta_destino = Path(args.destino)

    print(f"🔎 Analizando directorio origen: {ruta_origen}")
    print(f"📁 Directorio destino proyectado: {ruta_destino}\n")

    try:
        # Generar el plan de operaciones
        planes, lista_errores = generar_plan(
            origen=ruta_origen,
            destino_base=ruta_destino,
            extensiones=lista_extensiones,
            incluir_subcarpetas=not args.sin_subcarpetas,
            usar_exif=not args.sin_exif,
            usar_hash_duplicados=args.hash
        )

        # Informar sobre errores durante la recoleccion inicial si los hubiera
        if lista_errores:
            print("⚠️ Se detectaron advertencias/errores durante el escaneo inicial:")
            for err in lista_errores:
                print(f"   - {err['archivo']}: {err['error']}")
            print()

        # Si se solicita la opcion --simular, solo se muestra la vista previa
        if args.simular:
            print("🛡️ MODO SIMULACION ACTIVADO (No se modificara ningun archivo en disco)")
            reporte_simulacion = simular_plan(planes)
            print(reporte_simulacion)
        else:
            print("🚀 EJECUTANDO OPERACIONES EN DISCO...")
            reporte_ejecucion = ejecutar_plan(planes)
            print(reporte_ejecucion)

    except RutaNoValidaError as e:
        print(f"❌ ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ ERROR INESPERADO: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
