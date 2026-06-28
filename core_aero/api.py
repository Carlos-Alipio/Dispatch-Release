from django.http import HttpResponse
from ninja import NinjaAPI, Schema
import folium

from core_aero.repositories.airac_repo import AiracRepository
from core_aero.domain.matematica import calcular_distancia_e_rumo, calcular_rumo_magnetico
from core_aero.domain.planejamento import extrair_instrucoes_rota, validar_segmentos_rota
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


@api.get("/rotas/mapa_completo/")
def renderizar_mapa_rota_completa(request, route_string: str, initial_level: int = 350, origem: str = "", destino: str = ""):
    """
    Recebe uma string de rota, nível inicial, origem e destino via Query Parameters.
    Renderiza um mapa com todos os fixos da rota e as linhas conectando-os.
    """
    try:
        repo = AiracRepository(ciclo="atual")
        
        # Garante que a origem e o destino façam parte da instrução da rota (como DCT)
        # para que o motor de planejamento sempre processe esses pares iniciais e finais
        origem_upper = origem.strip().upper() if origem else ""
        destino_upper = destino.strip().upper() if destino else ""
        
        partes = route_string.strip().split()
        if origem_upper and partes and partes[0].split('/')[0].strip() != origem_upper:
            route_string = f"{origem_upper} DCT {route_string}"
            
        partes = route_string.strip().split()
        if destino_upper and partes and partes[-1].split('/')[0].strip() != destino_upper:
            route_string = f"{route_string} DCT {destino_upper}"
        
        # 1. Extrai instruções na matemática
        instrucoes, level_map = extrair_instrucoes_rota(route_string, initial_level)
        
        # 2. Busca fixos na base de dados
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

        # 3. Passa dados puros para o Domínio validar e processar
        segments = validar_segmentos_rota(fixos_brutos, initial_level, level_map)
        
        if not segments:
            return HttpResponse("<h2>Nenhum segmento retornado para a rota fornecida.</h2>", status=400)
            
        # Coletar waypoints únicos mantendo a ordem e buscar suas coordenadas
        waypoints_ordered = []
        for seg in segments:
            wp_from = seg.from_waypoint
            if not waypoints_ordered or waypoints_ordered[-1] != wp_from:
                waypoints_ordered.append(wp_from)
        
        # Adicionar o último waypoint do último segmento
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
                    
        # 1. Adiciona a origem
        if origem:
            add_wp(origem)
            
        # 2. Adiciona os fixos da rota
        for wp in waypoints_ordered:
            add_wp(wp)
            
        # 3. Adiciona o destino
        if destino:
            add_wp(destino)
                
        if not valid_waypoints:
            return HttpResponse("<h2>Nenhum waypoint válido encontrado para desenhar no mapa.</h2>", status=400)
            
        # Centraliza o mapa no ponto médio da rota aproximadamente, ou no primeiro waypoint
        primeiro_wp = valid_waypoints[0]
        centro_lat, centro_lon = coords_dict[primeiro_wp]
        
        # Criamos o objeto do mapa
        mapa = folium.Map(
            location=[centro_lat, centro_lon], 
            zoom_start=5,
            tiles="OpenStreetMap"
        )
        
        route_coords = []
        # Adiciona marcadores para os waypoints válidos
        for i, wp in enumerate(valid_waypoints):
            lat, lon = coords_dict[wp]
            route_coords.append([lat, lon])
            
            is_origin = (i == 0 and origem and wp == origem.strip().upper())
            is_dest = (i == len(valid_waypoints) - 1 and destino and wp == destino.strip().upper())
            
            if is_origin:
                popup = f"<b>{wp} (Origem)</b><br>Lat: {lat:.4f}<br>Lon: {lon:.4f}"
                folium.Marker(
                    location=[lat, lon],
                    popup=popup,
                    tooltip=wp,
                    icon=folium.Icon(color="green", icon="plane-departure", prefix="fa")
                ).add_to(mapa)
            elif is_dest:
                popup = f"<b>{wp} (Destino)</b><br>Lat: {lat:.4f}<br>Lon: {lon:.4f}"
                folium.Marker(
                    location=[lat, lon],
                    popup=popup,
                    tooltip=wp,
                    icon=folium.Icon(color="red", icon="plane-arrival", prefix="fa")
                ).add_to(mapa)
            else:
                # Fixo de rota: Círculo pequeno com o nome do fixo ao lado
                html_icon = f"""
                <div style="display: flex; align-items: center; transform: translate(-4px, -4px);">
                    <div style="width: 8px; height: 8px; background-color: #8b5cf6; border-radius: 50%; border: 1px solid white; box-shadow: 0 0 2px rgba(0,0,0,0.5);"></div>
                    <div style="margin-left: 5px; font-weight: bold; font-size: 11px; color: #0f172a; text-shadow: 1px 1px 0 #fff, -1px -1px 0 #fff, 1px -1px 0 #fff, -1px 1px 0 #fff;">{wp}</div>
                </div>
                """
                folium.Marker(
                    location=[lat, lon],
                    icon=folium.DivIcon(html=html_icon)
                ).add_to(mapa)
            
        # Desenha a linha da rota conectando os waypoints sequencialmente
        folium.PolyLine(
            locations=route_coords,
            color="purple",
            weight=4,
            opacity=0.8,
            tooltip=f"Rota: {route_string}"
        ).add_to(mapa)
        
        # Retorna o HTML gerado pelo Folium
        mapa_html = mapa._repr_html_()
        return HttpResponse(mapa_html)
        
    except Exception as e:
        return HttpResponse(f"<h2>Erro ao processar rota e gerar mapa: {str(e)}</h2>", status=400)


@api.get("/rotas/ui/")
def interface_mapa_rota(request):
    """
    Renderiza uma interface web amigável para digitação da rota e nível de voo.
    Ao submeter, chama o endpoint /rotas/mapa_completo/.
    """
    html_content = """
    <!DOCTYPE html>
    <html lang="pt-br">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Visualizador de Rotas Aéreas</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
            body { font-family: 'Inter', sans-serif; }
        </style>
    </head>
    <body class="bg-slate-900 text-slate-200 min-h-screen flex items-center justify-center p-4">
        <div class="bg-slate-800 p-8 rounded-2xl shadow-2xl max-w-lg w-full border border-slate-700">
            <div class="flex items-center space-x-3 mb-6">
                <svg class="w-8 h-8 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                <h1 class="text-2xl font-bold text-white">Planejamento de Rota</h1>
            </div>
            
            <form action="/api/rotas/mapa_completo/" method="GET" class="space-y-6" target="_blank">
                <div class="grid grid-cols-2 gap-4">
                    <div>
                        <label for="origem" class="block text-sm font-medium text-slate-300 mb-2">Origem (ICAO)</label>
                        <input 
                            type="text" 
                            id="origem" 
                            name="origem" 
                            class="w-full bg-slate-900 border border-slate-600 rounded-lg px-4 py-2 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 uppercase transition-all"
                            placeholder="Ex: SBMO"
                        >
                    </div>
                    <div>
                        <label for="destino" class="block text-sm font-medium text-slate-300 mb-2">Destino (ICAO)</label>
                        <input 
                            type="text" 
                            id="destino" 
                            name="destino" 
                            class="w-full bg-slate-900 border border-slate-600 rounded-lg px-4 py-2 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 uppercase transition-all"
                            placeholder="Ex: SAEZ"
                        >
                    </div>
                </div>

                <div>
                    <label for="route_string" class="block text-sm font-medium text-slate-300 mb-2">Descrição da Rota</label>
                    <textarea 
                        id="route_string" 
                        name="route_string" 
                        rows="4" 
                        class="w-full bg-slate-900 border border-slate-600 rounded-lg px-4 py-3 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent uppercase transition-all"
                        placeholder="Ex: OBLAX UZ21 VUNOX"
                        required
                    ></textarea>
                    <p class="mt-2 text-xs text-slate-400">Separe os fixos e aerovias por espaços.</p>
                </div>
                
                <div>
                    <label for="initial_level" class="block text-sm font-medium text-slate-300 mb-2">Nível de Voo Inicial</label>
                    <input 
                        type="number" 
                        id="initial_level" 
                        name="initial_level" 
                        value="350"
                        class="w-full bg-slate-900 border border-slate-600 rounded-lg px-4 py-3 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
                        required
                    >
                </div>
                
                <button 
                    type="submit" 
                    class="w-full bg-blue-600 hover:bg-blue-500 text-white font-semibold py-3 px-4 rounded-lg shadow-lg hover:shadow-blue-500/30 transition-all duration-200 flex justify-center items-center space-x-2"
                >
                    <span>Gerar Mapa Tático</span>
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3"></path></svg>
                </button>
            </form>
        </div>
    </body>
    </html>
    """
    return HttpResponse(html_content)