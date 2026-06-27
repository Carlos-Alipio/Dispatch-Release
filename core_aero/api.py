from ninja import NinjaAPI, Schema
from core_aero.repositories.airac_repo import AiracRepository

api = NinjaAPI(title="Aero SaaS API", version="1.0.0")

# Esquema para moldar a saída JSON no navegador
class AerodromoOut(Schema):
    icao: str
    nome: str
    latitude: float
    longitude: float
    elevacao_ft: int

@api.get("/aerodromos/{icao}", response=AerodromoOut)
def obter_coordenadas_aerodromo(request, icao: str):
    """
    Busca os dados vitais de um aeródromo direto da base AIRAC (.s3db)
    """
    try:
        repo = AiracRepository(ciclo="atual")
        aerodromo = repo.buscar_aerodromo(icao)
        return aerodromo
        
    except FileNotFoundError as e:
        return api.create_response(request, {"erro": str(e)}, status=500)
    except ValueError as e:
        return api.create_response(request, {"erro": str(e)}, status=404)