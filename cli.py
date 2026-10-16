#!/usr/bin/env python3
"""
Modulo cli.py - Interfaz de Linea de Comandos (CLI) para Memexicanisimos Files.

Soporta:
1. Modo directo de organización de archivos (retrocompatible):
   python3 cli.py --origen <dir> --destino <dir> [--modo mover|copiar] [--simular] [--hash]
2. Subcomandos especializados para respaldos, clonación y borrado seguro:
   python3 cli.py clonar --origen <dir> --destino <dir> [--incremental] [--checkpoint] [--versionar]
   python3 cli.py respaldo --perfiles Documentos,Fotos --destino <dir> [--checkpoint] [--versionar]
   python3 cli.py borrar-seguro --objetivo <ruta> --area-segura <sandbox> [--simular]
   python3 cli.py deshacer [--n 1] [--simular]
"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from app_types import ApiResponse
from core import (
    borrar_seguro,
    clonar_carpeta,
    deshacer_n_operaciones,
    ejecutar_plan_con_modo,
    generar_plan_con_estructura,
    respaldo_inteligente_windows_linux,
)


def _ejecutar_clonar(args: list) -> int:
    parser = argparse.ArgumentParser(prog="cli.py clonar", description="Clonación de carpetas por streaming con ledger.")
    parser.add_argument("--origen", required=True, help="Directorio origen.")
    parser.add_argument("--destino", required=True, help="Directorio destino.")
    parser.add_argument("--incremental", action="store_true", help="Omitir archivos sin cambios.")
    parser.add_argument("--sin-checkpoint", action="store_true", help="Desactivar ledger de reanudación.")
    parser.add_argument("--versionar", action="store_true", help="Archivar versiones viejas en .historial/ ante cambios.")
    parser.add_argument("--omitir-basura", action="store_true", help="Omitir cachés y archivos basura.")
    parser.add_argument("--simular", action="store_true", help="Simulación previa sin alterar disco.")
    parser.add_argument("--durabilidad", choices=["archivo", "lote", "none"], default="lote",
                        help="Modo de fsync: 'lote' (balance ideal 60-90 MB/s), 'archivo' (máxima seguridad), 'none' (sin sync).")
    parser.add_argument("--sin-directorios-vacios", action="store_true", help="No crear carpetas vacías del origen.")
    parser.add_argument("--checkpoint-strict", action="store_true", help="Abortar si existen errores previos no resueltos en el ledger.")
    parsed = parser.parse_args(args)

    modo_txt = "Simulación de clonación" if parsed.simular else "Clonación streaming"
    print(f"🚀 Iniciando {modo_txt} de '{parsed.origen}' ➔ '{parsed.destino}' [durabilidad={parsed.durabilidad}]...")
    res = clonar_carpeta(
        origen=parsed.origen,
        destino=parsed.destino,
        incremental=parsed.incremental,
        usar_checkpoint=not parsed.sin_checkpoint,
        archivar_versiones=parsed.versionar,
        omitir_basura=parsed.omitir_basura,
        simular=parsed.simular,
        preservar_vacios=not parsed.sin_directorios_vacios,
        durabilidad=parsed.durabilidad,
        checkpoint_strict=parsed.checkpoint_strict,
        callback_progreso=lambda idx, tot, b_cop, b_tot, nom: print(f"[{idx}/{tot}] {nom}")
    )
    if res.success:
        d = res.data or {}
        prefix = "🛡️ Simulación completada" if parsed.simular else "✅ Clonación completada con éxito"
        print(f"\n{prefix}:")
        if "job_id" in d:
            print(f"   • Job ID: {d.get('job_id')}")
        print(f"   • Procesados/Copiados: {d.get('copiados', 0)}")
        print(f"   • Omitidos (ya en destino/ledger): {d.get('omitidos', 0)}")
        print(f"   • Bytes: {d.get('bytes_copiados', 0):,} bytes (Total proyectado: {d.get('total', 0)} archivos)")
        if "directorios_totales" in d:
            print(f"   • Directorios totales: {d.get('directorios_totales', 0)} (Vacíos: {d.get('directorios_vacios', 0)})")
        if "metricas" in d:
            m = d["metricas"]
            print(f"   • Telemetría: {m.get('duracion_total_s')}s | {m.get('throughput_mb_s')} MB/s | RAM pico: {m.get('ram_pico_mb')} MB")
        if parsed.simular:
            import json
            print("\n📋 Resumen estructurado (sim.json format):")
            resumen_sim = {
                "archivos_totales": d.get("total", 0),
                "bytes_totales": d.get("bytes_copiados", 0),
                "directorios_totales": d.get("directorios_totales", 0),
                "directorios_vacios": d.get("directorios_vacios", 0),
                "accion": "SIMULACIÓN - nada se escribirá"
            }
            print(json.dumps(resumen_sim, indent=2, ensure_ascii=False))
        return 0
    else:
        print(f"\n❌ Error en clonación: {res.error}", file=sys.stderr)
        return 1


def _ejecutar_respaldo(args: list) -> int:
    parser = argparse.ArgumentParser(prog="cli.py respaldo", description="Respaldo inteligente de perfiles de usuario omitiendo basura.")
    parser.add_argument("--perfiles", required=True, help="Perfiles separados por comas (ej. Documentos,Imágenes,Escritorio).")
    parser.add_argument("--destino", required=True, help="Directorio destino (ej. disco externo USB).")
    parser.add_argument("--sin-checkpoint", action="store_true", help="Desactivar ledger.")
    parser.add_argument("--versionar", action="store_true", help="Archivar versiones modificadas en .historial/.")
    parser.add_argument("--simular", action="store_true", help="Simulación previa sin alterar disco.")
    parser.add_argument("--durabilidad", choices=["archivo", "lote", "none"], default="lote",
                        help="Modo de fsync: 'lote' (balance ideal), 'archivo' (máxima seguridad), 'none' (sin sync).")
    parser.add_argument("--checkpoint-strict", action="store_true", help="Abortar si existen errores previos no resueltos en el ledger.")
    parsed = parser.parse_args(args)

    lista_perfiles = [p.strip() for p in parsed.perfiles.split(",") if p.strip()]
    modo_txt = "Simulación de Respaldo" if parsed.simular else "Respaldo Inteligente"
    print(f"🛡️ Iniciando {modo_txt} para {lista_perfiles} ➔ '{parsed.destino}' [durabilidad={parsed.durabilidad}]...")
    res = respaldo_inteligente_windows_linux(
        perfiles=lista_perfiles,
        destino=parsed.destino,
        usar_checkpoint=not parsed.sin_checkpoint,
        archivar_versiones=parsed.versionar,
        simular=parsed.simular,
        durabilidad=parsed.durabilidad,
        checkpoint_strict=parsed.checkpoint_strict,
        callback_progreso=lambda cop, omit, err, tot, nom: print(f"[{cop+omit}/{tot}] {nom}")
    )
    if res.success:
        d = res.data or {}
        prefix = "🛡️ Simulación completada" if parsed.simular else "✅ Respaldo completado con éxito"
        print(f"\n{prefix}:")
        if "job_id" in d:
            print(f"   • Job ID: {d.get('job_id')}")
        print(f"   • Procesados/Copiados: {d.get('copiados', 0)}")
        print(f"   • Omitidos (basura/idénticos/ledger): {d.get('omitidos', 0)}")
        print(f"   • Bytes: {d.get('bytes_copiados', 0):,} bytes (Total proyectado: {d.get('total', 0)} archivos)")
        if "metricas" in d:
            m = d["metricas"]
            print(f"   • Telemetría: {m.get('duracion_total_s')}s | {m.get('throughput_mb_s')} MB/s | RAM pico: {m.get('ram_pico_mb')} MB")
        return 0
        print(f"   • Bytes transferidos: {d.get('bytes_copiados', 0):,} bytes")
        return 0
    else:
        print(f"\n❌ Error en respaldo: {res.error}", file=sys.stderr)
        return 1


def _ejecutar_borrar_seguro(args: list) -> int:
    parser = argparse.ArgumentParser(prog="cli.py borrar-seguro", description="Borrado controlado dentro de sandbox autorizado.")
    parser.add_argument("--objetivo", required=True, help="Archivo o subdirectorio a eliminar.")
    parser.add_argument("--area-segura", required=True, help="Área autorizada que contiene el objetivo.")
    parser.add_argument("--simular", action="store_true", help="Simular sin borrar datos.")
    parsed = parser.parse_args(args)

    res = borrar_seguro(
        objetivo=parsed.objetivo,
        area_autorizada=parsed.area_segura,
        dry_run=parsed.simular
    )
    if res.success:
        d = res.data or {}
        if d.get("simulado"):
            print(f"🛡️ Simulación de borrado seguro: se eliminaría '{d.get('eliminado')}' ({d.get('tipo')}).")
        else:
            print(f"🧹 Borrado seguro exitoso: {d.get('eliminados', 0)} elementos eliminados en '{d.get('ruta')}'.")
        return 0
    else:
        print(f"❌ Error de seguridad al borrar: {res.error} [{res.error_code}]", file=sys.stderr)
        return 1


def _ejecutar_deshacer(args: list) -> int:
    parser = argparse.ArgumentParser(prog="cli.py deshacer", description="Reversión atómica de operaciones previas.")
    parser.add_argument("--n", type=int, default=1, help="Número de operaciones a deshacer (por defecto 1).")
    parser.add_argument("--simular", action="store_true", help="Simular reversión sin alterar disco.")
    parsed = parser.parse_args(args)

    res = deshacer_n_operaciones(n=parsed.n, dry_run=parsed.simular)
    if res.success:
        d = res.data or {}
        print(f"↩️ Deshacer completado: {d.get('exitos', 0)} operaciones revertidas.")
        for log in d.get("logs", []):
            print(f"   • {log}")
        return 0
    else:
        print(f"❌ Error al deshacer: {res.error}", file=sys.stderr)
        return 1


def main() -> int:
    # Si se invoca con un subcomando explícito
    if len(sys.argv) > 1 and sys.argv[1] in ("clonar", "respaldo", "borrar-seguro", "deshacer"):
        sub = sys.argv[1]
        resto = sys.argv[2:]
        if sub == "clonar":
            return _ejecutar_clonar(resto)
        elif sub == "respaldo":
            return _ejecutar_respaldo(resto)
        elif sub == "borrar-seguro":
            return _ejecutar_borrar_seguro(resto)
        elif sub == "deshacer":
            return _ejecutar_deshacer(resto)

    # Modo raíz por defecto (organizador histórico de 5 criterios)
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
        help="Activa la deteccion de duplicados exactos por contenido usando hash MD5/Blake."
    )
    parser.add_argument(
        "--simular",
        action="store_true",
        help="Modo de prueba: Genera y muestra la simulacion del plan sin alterar ningun archivo."
    )

    args = parser.parse_args()

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
        res_plan: ApiResponse = generar_plan_con_estructura(
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
        res_ejec: ApiResponse = ejecutar_plan_con_modo(
            planes=planes,
            modo=args.modo.capitalize(),
            callback_progreso=lambda i, total, nom: print(f"[{i}/{total}] Procesando: {nom}")
        )

        if not res_ejec.success:
            print(f"\n❌ Error durante la ejecucion [{res_ejec.error_code}]: {res_ejec.error}", file=sys.stderr)
            return 1

        d_res = res_ejec.data or {}
        print("\n" + "=" * 70)
        print("🎉 EJECUCION COMPLETADA CON EXITO")
        print("=" * 70)
        print(f"Archivos procesados correctamente: {d_res.get('exitos', 0)}")
        print(f"Errores encontrados:              {d_res.get('errores', 0)}")
        print("=" * 70)
        return 0

    except Exception as exc:
        print(f"\n💥 Error inesperado en CLI: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
