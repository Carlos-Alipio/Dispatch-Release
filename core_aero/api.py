import logging

from django.http import HttpResponse
from django.shortcuts import redirect
from ninja import NinjaAPI, Schema
from typing import Literal, List, Union, Optional
from core_aero.repositories.airac_repo import AiracRepository
from core_aero.domain.planejamento import (
    extrair_instrucoes_rota,
    validar_segmentos_rota,
    calcular_distancia_e_rumo,
    calcular_rumo_magnetico
)
from core_aero.domain.entidades import FixoRota, SegmentoValidado
from core_aero.domain.excecoes import (
    BaseAiracIndisponivel,
    FixoNaoEncontrado,
    RecursoNaoEncontrado,
    RotaInvalida,
)

logger = logging.getLogger(__name__)

api = NinjaAPI(title="Aero SaaS API", version="1.0.0")


# --- MAPEAMENTO DE EXCEÇÕES DE DOMÍNIO PARA HTTP ---
# O domínio levanta exceções semânticas (excecoes.py); aqui elas viram status codes.

@api.exception_handler(RecursoNaoEncontrado)
def _handler_nao_encontrado(request, exc: RecursoNaoEncontrado):
    logger.info("Recurso não encontrado: %s", exc)
    return api.create_response(request, {"erro": str(exc)}, status=404)


@api.exception_handler(RotaInvalida)
def _handler_rota_invalida(request, exc: RotaInvalida):
    logger.info("Rota rejeitada pela validação: %s", exc)
    return api.create_response(request, {"erro": str(exc)}, status=422)


@api.exception_handler(BaseAiracIndisponivel)
def _handler_airac_indisponivel(request, exc: BaseAiracIndisponivel):
    logger.critical("Base AIRAC indisponível: %s", exc)
    return api.create_response(
        request, {"erro": "Base de dados AIRAC indisponível no servidor."}, status=503
    )


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


# --- SCHEMAS GEOJSON (RFC 7946) ---
class PointGeometry(Schema):
    type: Literal["Point"] = "Point"
    coordinates: List[float]

class LineStringGeometry(Schema):
    type: Literal["LineString"] = "LineString"
    coordinates: List[List[float]]

class PolygonGeometry(Schema):
    type: Literal["Polygon"] = "Polygon"
    coordinates: List[List[List[float]]]

class Feature(Schema):
    type: Literal["Feature"] = "Feature"
    geometry: Union[PointGeometry, LineStringGeometry, PolygonGeometry]
    properties: dict = {}

class FeatureCollection(Schema):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: List[Feature]


# --- ROTAS TRADICIONAIS (JSON) ---
# Convenção de URLs: todo endpoint de dados vive sob /v1/ (versionamento);
# páginas HTML não são API e ficam fora do Ninja (ver core_aero/views.py).

@api.get("/v1/aerodromos/{icao}", response=AerodromoOut)
def obter_coordenadas_aerodromo(request, icao: str):
    """Busca os dados vitais de um aeródromo direto da base AIRAC (.s3db)"""
    with AiracRepository(ciclo="atual") as repo:
        return repo.buscar_aerodromo(icao)


@api.get("/v1/rotas/calcular/{icao_origem}/{icao_destino}", response=RotaOut)
def calcular_rota_entre_aerodromos(request, icao_origem: str, icao_destino: str):
    """Calcula a distância e o rumo em formato JSON"""
    with AiracRepository(ciclo="atual") as repo:
        origem = repo.buscar_aerodromo(icao_origem)
        destino = repo.buscar_aerodromo(icao_destino)

    resultado = calcular_distancia_e_rumo(
        origem.latitude, origem.longitude, destino.latitude, destino.longitude
    )

    return {
        "origem": origem.icao,
        "destino": destino.icao,
        "distancia_nm": resultado["distancia_nm"],
        "rumo_verdadeiro_graus": resultado["rumo_verdadeiro_graus"]
    }


# --- PLANEJAMENTO DE ROTA COMPLETA ---
# O endpoint em si só orquestra; cada etapa (normalizar, buscar, validar,
# serializar) vive numa função com um único papel.

def _incluir_terminais_na_rota(route_string: str, origem: str, destino: str) -> str:
    """
    Garante que a string de rota comece na origem e termine no destino,
    inserindo trechos DCT (direto) quando o usuário não os digitou.
    """
    origem = origem.strip().upper()
    destino = destino.strip().upper()

    partes = route_string.strip().split()
    if origem and partes and partes[0].split('/')[0].strip() != origem:
        route_string = f"{origem} DCT {route_string}"

    partes = route_string.strip().split()
    if destino and partes and partes[-1].split('/')[0].strip() != destino:
        route_string = f"{route_string} DCT {destino}"

    return route_string


def _buscar_fixos_da_rota(repo: AiracRepository, instrucoes) -> List[FixoRota]:
    """
    Materializa cada instrução (fixo, aerovia, fixo) na sequência de FixoRota:
    aerovias vêm do banco na ordem dos seqno; trechos DCT são calculados
    (rumo magnético via Haversine + variação magnética local).
    """
    fixos: List[FixoRota] = []
    for start_wp_raw, airway, end_wp_raw in instrucoes:
        start = start_wp_raw.split('/')[0].strip()
        end = end_wp_raw.split('/')[0].strip()

        if airway.upper() == 'DCT':
            coord_start = repo.buscar_coordenadas(start)
            coord_end = repo.buscar_coordenadas(end)
            if not coord_start or not coord_end:
                raise FixoNaoEncontrado(f"Coordenadas não encontradas para {start} ou {end}")

            mag_var = repo.buscar_variacao_magnetica(coord_start.latitude, coord_start.longitude)
            course = calcular_rumo_magnetico(
                coord_start.latitude, coord_start.longitude,
                coord_end.latitude, coord_end.longitude,
                mag_var
            )
            fixos.append(FixoRota(id=start, airway_ref='DCT', is_reverse=False, course=None))
            fixos.append(FixoRota(id=end, airway_ref='DCT', is_reverse=False, course=course))
        else:
            fixos.extend(repo.buscar_fixos_aerovia(start, airway, end))

    return fixos


def _rota_para_geojson(
    repo: AiracRepository,
    segmentos: List[SegmentoValidado],
    route_string: str,
    origem: str,
    destino: str,
) -> FeatureCollection:
    """
    Serializa a rota validada em GeoJSON: um Point por waypoint (com o tipo
    origem/destino/fixo para o mapa colorir) e um LineString ligando todos.
    """
    waypoints_ordenados: List[str] = []
    for seg in segmentos:
        if not waypoints_ordenados or waypoints_ordenados[-1] != seg.from_waypoint:
            waypoints_ordenados.append(seg.from_waypoint)
    waypoints_ordenados.append(segmentos[-1].to_waypoint)

    coords_dict = {}
    waypoints_validos: List[str] = []

    def adicionar(wp: Optional[str]) -> None:
        if not wp:
            return
        wp = wp.strip().upper()
        if not waypoints_validos or waypoints_validos[-1] != wp:
            coord = repo.buscar_coordenadas(wp)
            if coord:
                coords_dict[wp] = (coord.latitude, coord.longitude)
                waypoints_validos.append(wp)

    adicionar(origem)
    for wp in waypoints_ordenados:
        adicionar(wp)
    adicionar(destino)

    if not waypoints_validos:
        raise RotaInvalida("Nenhum waypoint válido encontrado.")

    features = []
    route_coords = []

    for i, wp in enumerate(waypoints_validos):
        lat, lon = coords_dict[wp]
        route_coords.append([lon, lat])

        is_origin = (i == 0 and origem and wp == origem.strip().upper())
        is_dest = (i == len(waypoints_validos) - 1 and destino and wp == destino.strip().upper())
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


@api.get("/v1/rotas/geojson_completo/", response=FeatureCollection)
def calcular_rota_geojson_completo(request, route_string: str, initial_level: int = 350, origem: str = "", destino: str = ""):
    """
    Recebe a string de rota completa, níveis, origem e destino.
    Utiliza o Domínio (planejamento.py) para validar segmentos e devolve o GeoJSON.
    """
    route_string = _incluir_terminais_na_rota(route_string, origem, destino)
    logger.info("Calculando rota: %r (nível inicial F%s)", route_string, initial_level)

    instrucoes, level_map = extrair_instrucoes_rota(route_string, initial_level)

    with AiracRepository(ciclo="atual") as repo:
        fixos = _buscar_fixos_da_rota(repo, instrucoes)

        segmentos = validar_segmentos_rota(fixos, initial_level, level_map)
        if not segmentos:
            raise RotaInvalida("Nenhum segmento retornado para a rota fornecida.")

        return _rota_para_geojson(repo, segmentos, route_string, origem, destino)


@api.get("/rotas/ui/")
def cockpit_ui_legado(request):
    """A UI mudou de endereço: mantemos o redirect para não quebrar links antigos."""
    return redirect("/")


# --- CAMADAS GEOGRÁFICAS ESTÁTICAS (AIRAC) ---

@api.get("/v1/geo/airac/aerodromos-principais", response=FeatureCollection)
def buscar_aerodromos_principais(request, response: HttpResponse):
    """
    Retorna a infraestrutura fixa AIRAC (Camada 2) em GeoJSON estrito.
    Injeta cache de borda (28 dias) para otimização extrema no Frontend.
    """
    response["Cache-Control"] = "public, max-age=2419200"

    with AiracRepository(ciclo="atual") as repo:
        aerodromos = repo.buscar_aerodromos_ifr_hard()

    features = [
        Feature(
            geometry=PointGeometry(coordinates=[a.longitude, a.latitude]),
            properties={
                "icao": a.icao,
                "nome": a.nome,
                "elevacao_ft": a.elevacao_ft
            }
        )
        for a in aerodromos
    ]

    return FeatureCollection(features=features)


@api.get("/v1/geo/airac/ndbs", response=FeatureCollection)
def buscar_ndbs(request, response: HttpResponse):
    """Retorna todos os NDBs de rota no formato estrito GeoJSON"""

    # Cache na borda. O NDB não muda durante 28 dias.
    response["Cache-Control"] = "public, max-age=2419200"

    with AiracRepository(ciclo="atual") as repo:
        ndbs = repo.buscar_ndbs_enroute()

    features = [
        Feature(
            geometry=PointGeometry(coordinates=[ndb.longitude, ndb.latitude]),
            properties={
                "icao": ndb.identifier,  # Chamamos de icao para padronizar com a renderização JS
                "nome": ndb.nome,
                "frequencia_khz": ndb.frequencia_khz,
                "tipo": "NDB"
            }
        )
        for ndb in ndbs
    ]

    return FeatureCollection(features=features)


@api.get("/v1/geo/airac/vors", response=FeatureCollection)
def buscar_vors(request, response: HttpResponse):
    """Retorna todos os VORs de rota no formato estrito GeoJSON"""

    # Cache na borda. O VOR não muda durante 28 dias.
    response["Cache-Control"] = "public, max-age=2419200"

    with AiracRepository(ciclo="atual") as repo:
        vors = repo.buscar_vors()

    features = [
        Feature(
            geometry=PointGeometry(coordinates=[vor.longitude, vor.latitude]),
            properties={
                "icao": vor.identifier,  # Chamamos de icao para padronizar com a renderização JS
                "nome": vor.nome,
                "frequencia_mhz": vor.frequencia_mhz,
                "tipo": "VOR"
            }
        )
        for vor in vors
    ]

    return FeatureCollection(features=features)


@api.get("/v1/geo/airac/fixos", response=FeatureCollection)
def buscar_fixos(request, response: HttpResponse):
    """Retorna todos os Fixos de rota no formato estrito GeoJSON"""

    response["Cache-Control"] = "public, max-age=2419200"

    with AiracRepository(ciclo="atual") as repo:
        fixos = repo.buscar_fixos_mapa()

    features = [
        Feature(
            geometry=PointGeometry(coordinates=[fixo.longitude, fixo.latitude]),
            properties={
                "icao": fixo.identifier,
                "usage": fixo.usage,
                "tipo": "FIXO"
            }
        )
        for fixo in fixos
    ]

    return FeatureCollection(features=features)


@api.get("/v1/geo/airac/aerovias", response=FeatureCollection)
def buscar_aerovias(request, response: HttpResponse):
    """Retorna todas as aerovias no formato estrito GeoJSON (LineStrings)"""

    response["Cache-Control"] = "public, max-age=2419200"

    with AiracRepository(ciclo="atual") as repo:
        linhas = repo.buscar_linhas_aerovias()

    features = [
        Feature(
            geometry=LineStringGeometry(coordinates=linha.coordenadas),
            properties={
                "icao": linha.route_identifier,
                "usage": linha.usage,
                "direction": linha.direction,
                "tipo": "AEROVIA"
            }
        )
        for linha in linhas
    ]

    return FeatureCollection(features=features)


@api.get("/v1/geo/airac/areas-restritas", response=FeatureCollection)
def buscar_areas_restritas(request, response: HttpResponse):
    """Retorna o espaço aéreo restrito como Polígonos"""

    response["Cache-Control"] = "no-cache, no-store, must-revalidate"

    with AiracRepository(ciclo="atual") as repo:
        areas = repo.buscar_areas_restritas()

    features = [
        Feature(
            geometry=PolygonGeometry(coordinates=area.coordenadas),
            properties={
                "designation": area.designation,
                "nome": area.nome,
                "tipo": area.tipo
            }
        )
        for area in areas
    ]

    return FeatureCollection(features=features)


@api.get("/v1/geo/airac/firs", response=FeatureCollection)
def buscar_firs_endpoint(request, response: HttpResponse):
    """Retorna as FIRs e UIRs como Polígonos"""

    response["Cache-Control"] = "no-cache, no-store, must-revalidate"

    with AiracRepository(ciclo="atual") as repo:
        firs = repo.buscar_firs()

    features = [
        Feature(
            geometry=PolygonGeometry(coordinates=fir.coordenadas),
            properties={
                "identifier": fir.identifier,
                "nome": fir.nome,
                "indicador": fir.indicador
            }
        )
        for fir in firs
    ]

    return FeatureCollection(features=features)
