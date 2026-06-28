import math

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