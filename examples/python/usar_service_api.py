"""
Uso programático de la capa de servicio.

Requiere: pip install -e .
"""
from services.memex_service import MemexService
from services.memex_config import MemexConfig


def main():
    # Carga la configuración desde ~/.config/memex/mcp.json
    config = MemexConfig.cargar()
    service = MemexService(config)

    # Lanzar un respaldo asíncrono
    resultado = service.svc_respaldo(
        perfiles=["Documentos"],
        destino="/media/usuario/DiscoExterno/Backup",
        durabilidad="lote",
    )

    if not resultado["success"]:
        print(f"Error: {resultado['error']}")
        return

    job_id = resultado["data"]["job_id"]
    print(f"Job iniciado: {job_id}")

    # Consultar estado
    estado = service.svc_status(destino="/media/usuario/DiscoExterno/Backup", job_id=job_id)
    print(f"Estado: {estado['data']['estado']}")


if __name__ == "__main__":
    main()
