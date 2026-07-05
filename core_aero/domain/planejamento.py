import re
import math
from dataclasses import dataclass
from typing import List, Tuple, Dict, Optional
from core_aero.domain.entidades import FixoRota, SegmentoValidado, RegraCruzeiro
from core_aero.domain.excecoes import SentidoProibido, NivelAbaixoDoMinimo, NivelInvalidoParaRumo

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

@dataclass
class _PontoDaRota:
    """
    Um ponto único da rota, com as junções de aerovia já resolvidas.

    Quando a rota troca de aerovia (ex.: "... UZ1 BBB UW2 ..."), o fixo BBB
    vem do banco DUAS vezes: uma como fim da UZ1 e outra como início da UW2.
    São dois registros diferentes do mesmo lugar físico:

      - a CHEGADA em BBB acontece pela UZ1  -> rumo, sentido e aerovia da UZ1
      - a SAÍDA   de BBB acontece pela UW2  -> restrições e altitudes da UW2

    Guardar os dois registros elimina a ambiguidade sem precisar mutar os
    objetos de entrada.
    """
    chegada: FixoRota
    saida: FixoRota
    nivel: int

def _consolidar_pontos(fixos_rota: List[FixoRota], nivel_inicial: int, level_map: Dict[str, int]) -> List[_PontoDaRota]:
    """
    Converte a lista bruta de fixos (com duplicatas nas junções) em pontos únicos,
    resolvendo também o nível de voo ativo em cada ponto.
    """
    pontos: List[_PontoDaRota] = []
    nivel = nivel_inicial

    for fixo in fixos_rota:
        nivel = level_map.get(fixo.id, nivel)

        if pontos and pontos[-1].chegada.id == fixo.id:
            # Segunda ocorrência do mesmo fixo = junção de aerovias:
            # este registro descreve a SAÍDA do ponto pela nova aerovia.
            pontos[-1].saida = fixo
            pontos[-1].nivel = nivel
        else:
            pontos.append(_PontoDaRota(chegada=fixo, saida=fixo, nivel=nivel))

    return pontos

def _conferir_sentido_da_aerovia(saida: FixoRota, chegada: FixoRota) -> bool:
    """
    Aerovias one-way: 'F' só pode ser voada na ordem crescente de seqno,
    'B' só na decrescente. Retorna True se há restrição compatível com o
    sentido voado (o que dispensa a checagem semicircular no segmento).
    """
    restricao = (saida.restriction or "").strip().upper()
    if not restricao:
        return False

    voando_ao_contrario = chegada.is_reverse
    if (voando_ao_contrario and restricao == 'F') or (not voando_ao_contrario and restricao == 'B'):
        nome_sentido = 'Forward-only (F)' if restricao == 'F' else 'Backward-only (B)'
        raise SentidoProibido(f"Erro em {saida.id}: Sentido Proibido na {saida.airway_ref}. Aerovia {nome_sentido}.")

    return True

def _conferir_regra_semicircular(rumo: float, nivel: int, fixo_id: str, regras: List[RegraCruzeiro]) -> None:
    """
    Regra semicircular: rumos 000°-179° exigem nível ÍMPAR, 180°-359° exigem PAR.
    O dígito das dezenas do FL determina a paridade (F350 -> 35 -> ímpar).
    """
    nivel_e_impar = (nivel // 10) % 2 != 0
    exige_impar = is_course_odd(regras, rumo)

    if exige_impar and not nivel_e_impar:
        raise NivelInvalidoParaRumo(f"Erro em {fixo_id}: Rumo {int(rumo)}° exige nível ÍMPAR (Tentado F{nivel}).")
    if not exige_impar and nivel_e_impar:
        raise NivelInvalidoParaRumo(f"Erro em {fixo_id}: Rumo {int(rumo)}° exige nível PAR (Tentado F{nivel}).")

def validar_segmentos_rota(fixos_rota: List[FixoRota], nivel_inicial: int, level_map: Dict[str, int]) -> List[SegmentoValidado]:
    """
    Recebe fixos puros (já extraídos do BD) e valida a rota inteira:
    sentido da aerovia, altitude mínima e regra semicircular.

    Função pura: não modifica os FixoRota recebidos; devolve os segmentos validados.
    """
    pontos = _consolidar_pontos(fixos_rota, nivel_inicial, level_map)

    segmentos: List[SegmentoValidado] = []
    for atual, proximo in zip(pontos, pontos[1:]):
        saida = atual.saida        # regras para SAIR deste ponto
        chegada = proximo.chegada  # dados da aerovia pela qual se CHEGA ao próximo
        nivel = atual.nivel

        # 1. Sentido da aerovia (one-way voada ao contrário derruba a rota aqui)
        restricao_compativel = _conferir_sentido_da_aerovia(saida, chegada)

        # 2. Altitude mínima do segmento (MEA, em pés no AIRAC; nível em FL)
        if saida.altitude_minima and nivel < (saida.altitude_minima / 100):
            raise NivelAbaixoDoMinimo(
                f"Erro em {saida.id}: Nivel F{nivel} abaixo do minimo F{int(saida.altitude_minima / 100)} na {saida.airway_ref}."
            )

        # 3. Rumo do segmento + regra semicircular.
        # O AIRAC publica o inbound_course no sentido "para frente" da aerovia;
        # voando ao contrário (is_reverse), o rumo real é o recíproco (+180°).
        rumo: Optional[float] = chegada.course
        if not restricao_compativel and rumo is not None:
            if chegada.is_reverse:
                referencia = saida.course if saida.course is not None else rumo
                rumo = (referencia + 180) % 360
            _conferir_regra_semicircular(rumo, nivel, saida.id, chegada.regras_cruzeiro)

        segmentos.append(SegmentoValidado(
            from_waypoint=saida.id,
            to_waypoint=chegada.id,
            airway=chegada.airway_ref,
            course=round(rumo, 2) if rumo is not None else None,
            active_level=nivel,
            min_altitude=saida.altitude_minima,
            max_altitude=saida.altitude_maxima
        ))

    return segmentos

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
