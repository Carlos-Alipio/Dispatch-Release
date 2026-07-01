from django.http import HttpResponse
from ninja import NinjaAPI, Schema
from pydantic import Field
from typing import Literal, List, Dict, Any, Union
from core_aero.repositories.airac_repo import AiracRepository
from core_aero.domain.planejamento import (
    extrair_instrucoes_rota, 
    validar_segmentos_rota, 
    calcular_distancia_e_rumo, 
    calcular_rumo_magnetico
)
from core_aero.domain.entidades import FixoRota
from pathlib import Path

api = NinjaAPI(title="Aero SaaS API", version="1.0.0")

# --- ESQUEMAS DE SAÍDA JSON ---
class AerodromoOut(Schema):
    icao: str
    nome: str
    latitude: float
    longitude: float
    elevacao_ft: int

class RotaOut(Schema):
    origem: str
    destino: str
    distancia_nm: float
    rumo_verdadeiro_graus: float


# --- ROTAS TRADICIONAIS (JSON) ---

@api.get("/aerodromos/{icao}", response=AerodromoOut)
def obter_coordenadas_aerodromo(request, icao: str):
    """Busca os dados vitais de um aeródromo direto da base AIRAC (.s3db)"""
    try:
        repo = AiracRepository(ciclo="atual")
        return repo.buscar_aerodromo(icao)
    except FileNotFoundError as e:
        return api.create_response(request, {"erro": str(e)}, status=500)
    except ValueError as e:
        return api.create_response(request, {"erro": str(e)}, status=404)


@api.get("/rotas/calcular/{icao_origem}/{icao_destino}", response=RotaOut)
def calcular_rota_entre_aerodromos(request, icao_origem: str, icao_destino: str):
    """Calcula a distância e o rumo em formato JSON"""
    try:
        repo = AiracRepository(ciclo="atual")
        origem = repo.buscar_aerodromo(icao_origem)
        destino = repo.buscar_aerodromo(icao_destino)
        
        resultado = calcular_distancia_e_rumo(
            origem.latitude, origem.longitude, destino.latitude, destino.longitude
        )
        
        return {
            "origem":起源.icao,
            "destino": destino.icao,
            "distancia_nm": resultado["distancia_nm"],
            "rumo_verdadeiro_graus": resultado["rumo_verdadeiro_graus"]
        }
    except Exception as e:
        return api.create_response(request, {"erro": str(e)}, status=400)


# --- SCHEMAS GEOJSON (RFC 7946) ---
class PointGeometry(Schema):
    type: Literal["Point"] = "Point"
    coordinates: List[float]

class LineStringGeometry(Schema):
    type: Literal["LineString"] = "LineString"
    coordinates: List[List[float]]

class Feature(Schema):
    type: Literal["Feature"] = "Feature"
    geometry: Union[PointGeometry, LineStringGeometry]
    properties: dict = {}

class FeatureCollection(Schema):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: List[Feature]

class GeoJsonAerodromosOut(Schema):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: List[Feature]

@api.get("/v1/geo/airac/aerodromos-principais", response=GeoJsonAerodromosOut)
def buscar_aerodromos_principais(request, response: HttpResponse):
    """
    Retorna a infraestrutura fixa AIRAC (Camada 2) em GeoJSON estrito.
    Injeta cache de borda (28 dias) para otimização extrema no Frontend.
    """
    response["Cache-Control"] = "public, max-age=2419200"
    
    repo = AiracRepository(ciclo="atual")
    aerodromos = repo.buscar_aerodromos_ifr_hard()
    
    features = [
        Feature(
            geometry=PointGeometry(coordinates=[a.lon_deg, a.lat_deg]),
            properties={
                "icao": a.icao, 
                "nome": a.nome, 
                "elevacao_ft": a.elevacao_ft
            }
        )
        for a in aerodromos
    ]
    
    return GeoJsonAerodromosOut(features=features)

@api.get("/rotas/geojson_completo/", response=FeatureCollection)
def calcular_rota_geojson_completo(request, route_string: str, initial_level: int = 350, origem: str = "", destino: str = ""):
    """
    Recebe a string de rota completa, níveis, origem e destino.
    Utiliza o Domínio (planejamento.py) para validar segmentos e devolve o GeoJSON.
    """
    try:
        repo = AiracRepository(ciclo="atual")
        
        origem_upper = origem.strip().upper() if origem else ""
        destino_upper = destino.strip().upper() if destino else ""
        
        partes = route_string.strip().split()
        if origem_upper and partes and partes[0].split('/')[0].strip() != origem_upper:
            route_string = f"{origem_upper} DCT {route_string}"
            
        partes = route_string.strip().split()
        if destino_upper and partes and partes[-1].split('/')[0].strip() != destino_upper:
            route_string = f"{route_string} DCT {destino_upper}"
        
        instrucoes, level_map = extrair_instrucoes_rota(route_string, initial_level)
        
        fixos_brutos = []
        for start_wp_raw, airway, end_wp_raw in instrucoes:
            start = start_wp_raw.split('/')[0].strip()
            end = end_wp_raw.split('/')[0].strip()
            
            if airway.upper() == 'DCT':
                coord_start = repo.buscar_coordenadas(start)
                coord_end = repo.buscar_coordenadas(end)
                if not coord_start or not coord_end:
                    raise ValueError(f"Coordenadas não encontradas para {start} ou {end}")
                
                mag_var = repo.buscar_variacao_magnetica(coord_start.latitude, coord_start.longitude)
                course = calcular_rumo_magnetico(
                    coord_start.latitude, coord_start.longitude, 
                    coord_end.latitude, coord_end.longitude, 
                    mag_var
                )
                fixos_brutos.append(FixoRota(id=start, airway_ref='DCT', is_reverse=False, course=None))
                fixos_brutos.append(FixoRota(id=end, airway_ref='DCT', is_reverse=False, course=course))
            else:
                fixos_brutos.extend(repo.buscar_fixos_aerovia(start, airway, end))

        segments = validar_segmentos_rota(fixos_brutos, initial_level, level_map)
        if not segments:
            return api.create_response(request, {"erro": "Nenhum segmento retornado para a rota fornecida."}, status=400)
            
        waypoints_ordered = []
        for seg in segments:
            wp_from = seg.from_waypoint
            if not waypoints_ordered or waypoints_ordered[-1] != wp_from:
                waypoints_ordered.append(wp_from)
        
        if segments:
            waypoints_ordered.append(segments[-1].to_waypoint)
            
        coords_dict = {}
        valid_waypoints = []
        
        def add_wp(w):
            if not w: return
            w = w.strip().upper()
            if not valid_waypoints or valid_waypoints[-1] != w:
                c = repo.buscar_coordenadas(w)
                if c:
                    coords_dict[w] = (c.latitude, c.longitude)
                    valid_waypoints.append(w)
                    
        if origem:
            add_wp(origem)
        for wp in waypoints_ordered:
            add_wp(wp)
        if destino:
            add_wp(destino)
                
        if not valid_waypoints:
            return api.create_response(request, {"erro": "Nenhum waypoint válido encontrado."}, status=400)
            
        features = []
        route_coords = []
        
        for i, wp in enumerate(valid_waypoints):
            lat, lon = coords_dict[wp]
            route_coords.append([lon, lat])
            
            is_origin = (i == 0 and origem and wp == origem.strip().upper())
            is_dest = (i == len(valid_waypoints) - 1 and destino and wp == destino.strip().upper())
            
            tipo = "origem" if is_origin else "destino" if is_dest else "fixo"
            
            features.append(
                Feature(
                    geometry=PointGeometry(coordinates=[lon, lat]),
                    properties={"icao": wp, "tipo": tipo}
                )
            )
            
        if len(route_coords) > 1:
            features.append(
                Feature(
                    geometry=LineStringGeometry(coordinates=route_coords),
                    properties={"route": route_string}
                )
            )
            
        return FeatureCollection(features=features)
        
    except Exception as e:
        return api.create_response(request, {"erro": str(e)}, status=400)

@api.get("/rotas/ui/")
def cockpit_ui(request):
    """Serve a interface HTML estática do Cockpit (MapLibre)"""
    template_path = Path(__file__).parent / "templates" / "template.html"
    if template_path.exists():
        return HttpResponse(template_path.read_text(encoding="utf-8"), content_type="text/html")
    return HttpResponse("<h2>Template não encontrado.</h2>", status=404)

# Não precisamos criar um Schema de saída novo, o FeatureCollection já serve para NDBs.

@api.get("/v1/geo/airac/ndbs", response=FeatureCollection)
def buscar_ndbs(request, response: HttpResponse):
    """Retorna todos os NDBs de rota no formato estrito GeoJSON"""
    
    # 1. Cache na borda. O NDB não muda durante 28 dias.
    response["Cache-Control"] = "public, max-age=2419200"
    
    # 2. Instanciamos o repositório e pedimos os dados limpos
    repo = AiracRepository(ciclo="atual")
    ndbs = repo.buscar_ndbs_enroute()
    
    # 3. Empacotamos no padrão GeoJSON (RFC 7946)
    features = []
    for ndb in ndbs:
        features.append(
            Feature(
                geometry=PointGeometry(coordinates=[ndb.lon_deg, ndb.lat_deg]),
                properties={
                    "icao": ndb.identifier, # Chamamos de icao para padronizar com a renderização JS
                    "nome": ndb.nome,
                    "frequencia_khz": ndb.frequencia_khz,
                    "tipo": "NDB"
                }
            )
        )
        
    return FeatureCollection(features=features)

@api.get("/v1/geo/airac/vors", response=FeatureCollection)
def buscar_vors(request, response: HttpResponse):
    """Retorna todos os VORs de rota no formato estrito GeoJSON"""
    
    # 1. Cache na borda. O VOR não muda durante 28 dias.
    response["Cache-Control"] = "public, max-age=2419200"
    
    # 2. Instanciamos o repositório e pedimos os dados limpos
    repo = AiracRepository(ciclo="atual")
    vors = repo.buscar_vors()
    
    # 3. Empacotamos no padrão GeoJSON (RFC 7946)
    features = []
    for vor in vors:
        features.append(
            Feature(
                geometry=PointGeometry(coordinates=[vor.lon_deg, vor.lat_deg]),
                properties={
                    "icao": vor.identifier, # Chamamos de icao para padronizar com a renderização JS
                    "nome": vor.nome,
                    "frequencia_mhz": vor.frequencia_mhz,
                    "tipo": "VOR"
                }
            )
        )

    return FeatureCollection(features=features)