from django.http import HttpResponse
from ninja import NinjaAPI, Schema
import folium

from core_aero.repositories.airac_repo import AiracRepository
from core_aero.domain.matematica import calcular_distancia_e_rumo

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


# --- NOVA ROTA VISUAL (Retorna um mapa interativo em HTML) ---

@api.get("/rotas/mapa/{icao_origem}/{icao_destino}")
def renderizar_mapa_rota(request, icao_origem: str, icao_destino: str):
    """
    Busca os aeródromos no AIRAC, calcula a distância e renderiza 
    um mapa interativo completo diretamente no navegador.
    """
    try:
        repo = AiracRepository(ciclo="atual")
        origem = repo.buscar_aerodromo(icao_origem)
        destino = repo.buscar_aerodromo(icao_destino)
        
        # Faz o cálculo matemático que criamos antes
        dados_rota = calcular_distancia_e_rumo(
            origem.latitude, origem.longitude, destino.latitude, destino.longitude
        )
        
        # 1. Centraliza o mapa no ponto médio entre a origem e o destino
        centro_lat = (origem.latitude + destino.latitude) / 2
        centro_lon = (origem.longitude + destino.longitude) / 2
        
        # Criamos o objeto do mapa (usando um tema limpo e profissional)
        mapa = folium.Map(
            location=[centro_lat, centro_lon], 
            zoom_start=4,
            tiles="OpenStreetMap"
        )
        
        # 2. Adiciona o Marcador do Aeródromo de Origem
        popup_origem = f"<b>{origem.icao}</b><br>{origem.nome}<br>Elev: {origem.elevacao_ft}ft"
        folium.Marker(
            location=[origem.latitude, origem.longitude],
            popup=popup_origem,
            tooltip=origem.icao,
            icon=folium.Icon(color="green", icon="plane-departure", prefix="fa")
        ).add_to(mapa)
        
        # 3. Adiciona o Marcador do Aeródromo de Destino
        popup_destino = f"<b>{destino.icao}</b><br>{destino.nome}<br>Elev: {destino.elevacao_ft}ft"
        folium.Marker(
            location=[destino.latitude, destino.longitude],
            popup=popup_destino,
            tooltip=destino.icao,
            icon=folium.Icon(color="red", icon="plane-arrival", prefix="fa")
        ).add_to(mapa)
        
        # 4. Desenha a linha da rota conectando os dois pontos
        # Para rotas longas, o ideal no futuro é interpolar pontos da ortodromia curva,
        # mas esta linha já nos dá a conexão direta inicial.
        folium.PolyLine(
            locations=[[origem.latitude, origem.longitude], [destino.latitude, destino.longitude]],
            color="blue",
            weight=3,
            opacity=0.8,
            tooltip=f"Distância: {dados_rota['distancia_nm']} NM | Rumo: {dados_rota['rumo_verdadeiro_graus']}°"
        ).add_to(mapa)
        
        # 5. MÁGICA: Extrai o HTML bruto do Folium e envelopa em uma resposta web do Django
        mapa_html = mapa._repr_html_()
        return HttpResponse(mapa_html)
        
    except Exception as e:
        return HttpResponse(f"<h2>Erro ao gerar mapa tático: {str(e)}</h2>", status=400)