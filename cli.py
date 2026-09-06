#!/usr/bin/env python3
"""
Modulo cli.py - Interfaz de Linea de Comandos (CLI) para organizacion masiva de archivos.

Permite ejecutar la organizacion de archivos por estructura desde la terminal,
ofreciendo opciones para previsualizar/simular planes o ejecutarlos directamente.
"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from app_types import ServiceResult, RutaNoValidaError
from core import generar_plan_con_estructura, ejecutar_plan_con_modo
from error_codes import ErrorCode


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Herramienta CLI para organizar archivos por fecha/estructura y gestionar duplicados de forma segura.",
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
        help="Ruta del directorio raiz donde se creara la estructura de carpetas."
    )

    # Argumentos opcionales
    parser.add_argument(
        "--extensiones",
        type=str,
        default=None,
        help="Lista de extensiones separadas por comas a filtrar. Ej: '.jpg,.png,.jpeg' (Por defecto incluye todas)."
    )
    parser.add_argument(
        "--modo",
        type=str,
        choices=["mover", "copiar"],
        default="mover",
        help="Modo de operacion: 'mover' (por defecto) o 'copiar'."
    )
    parser.add_argument(
        "--sin-subcarpetas",
        action="store_true",
        help="Si se especifica, solo analiza la carpeta de nivel superior (desactiva escaneo recursivo)."
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
        help="Modo de prueba: Genera y muestra la simulacion del plan sin alterar ningun archivo."
    )

    args = parser.parse_args()

    # Procesar lista de extensiones si fue proporcionada
    lista_extensiones: Optional[List[str]] = None
    if args.extensiones:
        lista_extensiones = [
            ext.strip() if ext.strip().startswith(".") else f".{ext.strip()}"
            for ext in args.extensiones.split(",")
            if ext.strip()
        ]

    ruta_origen = Path(args.origen).resolve()
    ruta_destino = Path(args.destino).resolve()

    print(f"🔎 Analizando directorio origen: {ruta_origen}")
    print(f"📁 Directorio destino proyectado: {ruta_destino}")
    print(f"⚙️ Modo de operacion: [{args.modo.upper()}]\n")

    try:
        res_plan: ServiceResult = generar_plan_con_estructura(
            origen=ruta_origen,
            destino_base=ruta_destino,
            extensiones=lista_extensiones,
            incluir_subcarpetas=not args.sin_subcarpetas,
            usar_exif=not args.sin_exif,
            usar_hash_duplicados=args.hash
        )

        if not res_plan.success:
            print(f"❌ ERROR generando plan [{res_plan.error_code}]: {res_plan.error}", file=sys.stderr)
            return 1

        planes = res_plan.data or []
        if not planes:
            print("ℹ️ No se encontraron archivos que coincidan con los criterios.")
            return 0

        print(f"📋 Se encontraron {len(planes)} archivos listos para organizar.\n")

        if args.simular:
            print("=" * 70)
            print("🛡️  MODO SIMULACION ACTIVADO (No se modificara ningun archivo en disco)")
            print("=" * 70)
            for i, p in enumerate(planes, start=1):
                acc = p.get('accion', 'mover').upper()
                orig = p.get('origen')
                dest = p.get('destino')
                fec = p.get('fecha', 'N/A')
                print(f"[{i}/{len(planes)}] [{acc}] {orig.name}")
                print(f"   ➔ Destino: {dest}")
                print(f"   ➔ Fecha:   {fec}")
            print("=" * 70)
            print(f"Simulacion completada exitosamente. Total archivos simulados: {len(planes)}")
            return 0

        print("🚀 EJECUTANDO OPERACIONES EN DISCO...")
        res_ejec: ServiceResult = ejecutar_plan_con_modo(
            planes=planes,
            modo=args.modo.capitalize(),
            callback_progreso=lambda i, total, nom: print(f"[{i}/{total}] Procesando: {nom}")
        )

        if not res_ejec.success:
            print(f"\n❌ Error durante la ejecucion [{res_ejec.error_code}]: {res_ejec.error}", file=sys.stderr)
            return 1

        d_res = res_ejec.data or {}
        print("\n" + "=" * 70)
        print("✅ EJECUCION COMPLETADA")
        print(f"   • Exitosos: {d_res.get('exitos', 0)}")
        print(f"   • Errores:  {d_res.get('errores', 0)}")
        print("=" * 70)
        return 0

    except RutaNoValidaError as e:
        print(f"❌ ERROR: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"❌ ERROR INESPERADO: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
