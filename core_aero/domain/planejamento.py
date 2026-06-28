import re
import math
from typing import List, Tuple, Dict
from core_aero.domain.entidades import FixoRota, SegmentoValidado, RegraCruzeiro

def extrair_instrucoes_rota(route_string: str, nivel_inicial: int) -> Tuple[List[Tuple[str, str, str]], Dict[str, int]]:
    """
    Transforma string de rota em (origem, aerovia, destino) e mapeia níveis solicitados.
    """
    parts = route_string.strip().split()
    level_map = {}
    current_level = nivel_inicial
    
    def get_level(wp: str, cur: int) -> int:
        match = re.search(r'F(\d+)', wp)
        if match:
            return int(match.group(1))
        return cur
        
    def clean_wp(wp: str) -> str:
        return wp.split('/')[0].strip()

    for p in parts:
        clean = clean_wp(p)
        if 'F' in p:
            level_map[clean] = get_level(p, current_level)
            current_level = level_map[clean]

    instrucoes = []
    for i in range(0, len(parts) - 2, 2):
        start_wp = parts[i]
        airway = parts[i+1]
        end_wp = parts[i+2]
        instrucoes.append((start_wp, airway, end_wp))
        
    return instrucoes, level_map

def is_course_odd(regras: List[RegraCruzeiro], course: float) -> bool:
    """
    Determina se o rumo magnético exige nível ímpar.
    Regra Semicircular Padrão: 
    000° a 179° = Ímpar (ODD)
    180° a 359° = Par (EVEN)
    """
    return 0 <= course < 180

def validar_segmentos_rota(fixos_rota: List[FixoRota], nivel_inicial: int, level_map: Dict[str, int]) -> List[SegmentoValidado]:
    """
    Recebe fixos puros (já extraídos do BD) e valida a rota inteira (direção, altitude, regras).
    Retorna os segmentos validados da rota.
    """
    if not fixos_rota:
        return []

    full_route_data = []
    current_level = nivel_inicial
    
    for wp in fixos_rota:
        if wp.id in level_map:
            current_level = level_map[wp.id]
        wp.active_level = current_level
        
        if not full_route_data or full_route_data[-1].id != wp.id:
            full_route_data.append(wp)
        else:
            setattr(full_route_data[-1], '_next_wp_data', wp)

    segments = []
    for i in range(len(full_route_data) - 1):
        wp_raw = full_route_data[i]
        nxt = full_route_data[i+1]
        
        wp = getattr(wp_raw, '_next_wp_data', wp_raw)
        lvl = wp.active_level

        restr = wp.restriction
        has_valid_restriction = False
        if restr and restr.strip():
            is_rev = nxt.is_reverse
            if (is_rev and restr.upper() == 'F') or (not is_rev and restr.upper() == 'B'):
                direction_name = 'Forward-only (F)' if restr.upper() == 'F' else 'Backward-only (B)'
                raise ValueError(f"Erro em {wp.id}: Sentido Proibido na {wp.airway_ref}. Aerovia {direction_name}.")
            else:
                has_valid_restriction = True

        if wp.min and lvl < (wp.min / 100):
            raise ValueError(f"Erro em {wp.id}: Nivel F{lvl} abaixo do minimo F{int(wp.min/100)} na {wp.airway_ref}.")

        actual_course = nxt.course
        if not has_valid_restriction:
            course = nxt.course
            if course is not None:
                actual_course = course
                if nxt.is_reverse:
                    ref_course = wp.course if wp.course is not None else course
                    if ref_course is not None:
                        actual_course = (ref_course + 180) % 360
                
                is_odd = (lvl // 10) % 2 != 0
                required_odd = is_course_odd(nxt.regras_cruzeiro, actual_course)
                
                if required_odd and not is_odd:
                    raise ValueError(f"Erro em {wp.id}: Rumo {int(actual_course)}° exige nível ÍMPAR (Tentado F{lvl}).")
                elif not required_odd and is_odd:
                    raise ValueError(f"Erro em {wp.id}: Rumo {int(actual_course)}° exige nível PAR (Tentado F{lvl}).")

        segments.append(SegmentoValidado(
            from_waypoint=wp.id,
            to_waypoint=nxt.id,
            airway=nxt.airway_ref,
            course=round(actual_course, 2) if actual_course is not None else None,
            active_level=lvl,
            min_altitude=wp.min,
            max_altitude=wp.max
        ))

    return segments

def calcular_distancia_e_rumo(lat1: float, lon1: float, lat2: float, lon2: float) -> dict:
    """
    Calcula a distância ortodrómica (círculo máximo) e o rumo verdadeiro inicial
    entre duas coordenadas geográficas.
    
    Retorna: Dicionário com 'distancia_nm' e 'rumo_verdadeiro_graus'
    """
    # Raio médio volumétrico da Terra em Milhas Náuticas
    RAIO_TERRA_NM = 3440.065

    # 1. Converter graus para radianos
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    # 2. Fórmula de Haversine (Para a Distância)
    a = math.sin(delta_phi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    distancia_nm = RAIO_TERRA_NM * c

    # 3. Fórmula do Rumo Verdadeiro Inicial (Initial True Bearing)
    y = math.sin(delta_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda)
    theta = math.atan2(y, x)
    rumo_verdadeiro = (math.degrees(theta) + 360) % 360

    return {
        "distancia_nm": round(distancia_nm, 1),
        "rumo_verdadeiro_graus": round(rumo_verdadeiro, 1)
    }

def calcular_rumo_magnetico(lat1: float, lon1: float, lat2: float, lon2: float, variacao_magnetica: float) -> float:
    """
    Calcula o rumo magnético usando o rumo verdadeiro e a variação magnética local.
    """
    dados = calcular_distancia_e_rumo(lat1, lon1, lat2, lon2)
    rumo_verdadeiro = dados["rumo_verdadeiro_graus"]
    return round((rumo_verdadeiro - variacao_magnetica) % 360, 2)
