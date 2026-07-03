"""
Testes das funções puras do domínio (planejamento.py).

Não tocam banco, rede nem Django — devem rodar em qualquer ambiente (inclusive CI
sem o arquivo AIRAC).
"""
import pytest

from core_aero.domain.entidades import FixoRota
from core_aero.domain.excecoes import (
    NivelAbaixoDoMinimo,
    NivelInvalidoParaRumo,
    SentidoProibido,
)
from core_aero.domain.planejamento import (
    calcular_distancia_e_rumo,
    calcular_rumo_magnetico,
    extrair_instrucoes_rota,
    is_course_odd,
    validar_segmentos_rota,
)


# --- extrair_instrucoes_rota ---

class TestExtrairInstrucoesRota:
    def test_rota_simples_gera_uma_tripla(self):
        instrucoes, level_map = extrair_instrucoes_rota("OBLAX UZ21 VUNOX", 350)
        assert instrucoes == [("OBLAX", "UZ21", "VUNOX")]
        assert level_map == {}

    def test_rota_encadeada_gera_triplas_sobrepostas(self):
        instrucoes, _ = extrair_instrucoes_rota("AAA UZ1 BBB UW2 CCC", 350)
        assert instrucoes == [("AAA", "UZ1", "BBB"), ("BBB", "UW2", "CCC")]

    def test_nivel_solicitado_no_fixo_entra_no_level_map(self):
        _, level_map = extrair_instrucoes_rota("AAA/F370 UZ1 BBB", 350)
        assert level_map == {"AAA": 370}

    def test_rota_vazia_nao_gera_instrucoes(self):
        instrucoes, level_map = extrair_instrucoes_rota("", 350)
        assert instrucoes == []
        assert level_map == {}


# --- is_course_odd (regra semicircular) ---

class TestRegraSemicircular:
    @pytest.mark.parametrize("rumo", [0, 45, 90, 179, 179.9])
    def test_rumo_leste_exige_nivel_impar(self, rumo):
        assert is_course_odd([], rumo) is True

    @pytest.mark.parametrize("rumo", [180, 225, 270, 359, 359.9])
    def test_rumo_oeste_exige_nivel_par(self, rumo):
        assert is_course_odd([], rumo) is False


# --- calcular_distancia_e_rumo (Haversine + rumo verdadeiro inicial) ---

class TestDistanciaERumo:
    def test_mesmo_ponto_tem_distancia_zero(self):
        r = calcular_distancia_e_rumo(-23.4, -46.5, -23.4, -46.5)
        assert r["distancia_nm"] == 0.0

    def test_um_grau_de_longitude_no_equador_sao_cerca_de_60_nm(self):
        r = calcular_distancia_e_rumo(0.0, 0.0, 0.0, 1.0)
        assert 59.8 <= r["distancia_nm"] <= 60.3
        assert r["rumo_verdadeiro_graus"] == 90.0

    def test_rumo_norte(self):
        r = calcular_distancia_e_rumo(0.0, 0.0, 1.0, 0.0)
        assert r["rumo_verdadeiro_graus"] == 0.0

    def test_rumo_oeste(self):
        r = calcular_distancia_e_rumo(0.0, 0.0, 0.0, -1.0)
        assert r["rumo_verdadeiro_graus"] == 270.0

    def test_distancia_e_simetrica(self):
        ida = calcular_distancia_e_rumo(-23.43, -46.47, -22.81, -43.25)
        volta = calcular_distancia_e_rumo(-22.81, -43.25, -23.43, -46.47)
        assert ida["distancia_nm"] == volta["distancia_nm"]

    def test_sbgr_para_sbgl_tem_distancia_conhecida(self):
        # Guarulhos → Galeão: ~180 NM em círculo máximo
        r = calcular_distancia_e_rumo(-23.4356, -46.4731, -22.8100, -43.2506)
        assert 170 <= r["distancia_nm"] <= 190
        # Rumo aproximadamente leste-nordeste
        assert 70 <= r["rumo_verdadeiro_graus"] <= 90


class TestRumoMagnetico:
    def test_variacao_oeste_negativa_aumenta_o_rumo(self):
        # Rumo verdadeiro 90° com variação -20° (W) → rumo magnético 110°
        rumo = calcular_rumo_magnetico(0.0, 0.0, 0.0, 1.0, -20.0)
        assert rumo == 110.0

    def test_resultado_normalizado_para_0_360(self):
        # Rumo verdadeiro 0° com variação +10° (E) → 350°, não -10°
        rumo = calcular_rumo_magnetico(0.0, 0.0, 1.0, 0.0, 10.0)
        assert rumo == 350.0


# --- validar_segmentos_rota ---

def _fixo(id: str, course=None, is_reverse=False, airway="UZ1", **kwargs) -> FixoRota:
    return FixoRota(id=id, is_reverse=is_reverse, airway_ref=airway, course=course, **kwargs)


class TestValidarSegmentosRota:
    def test_lista_vazia_retorna_vazio(self):
        assert validar_segmentos_rota([], 350, {}) == []

    def test_rota_valida_gera_segmento(self):
        # Rumo 100° (leste) exige nível ímpar; F350 é ímpar → válido
        fixos = [_fixo("AAA"), _fixo("BBB", course=100.0)]
        segs = validar_segmentos_rota(fixos, 350, {})
        assert len(segs) == 1
        assert segs[0].from_waypoint == "AAA"
        assert segs[0].to_waypoint == "BBB"
        assert segs[0].course == 100.0
        assert segs[0].active_level == 350

    def test_nivel_par_em_rumo_leste_viola_semicircular(self):
        fixos = [_fixo("AAA"), _fixo("BBB", course=100.0)]
        with pytest.raises(NivelInvalidoParaRumo):
            validar_segmentos_rota(fixos, 340, {})

    def test_nivel_impar_em_rumo_oeste_viola_semicircular(self):
        fixos = [_fixo("AAA"), _fixo("BBB", course=200.0)]
        with pytest.raises(NivelInvalidoParaRumo):
            validar_segmentos_rota(fixos, 350, {})

    def test_nivel_par_em_rumo_oeste_e_valido(self):
        fixos = [_fixo("AAA"), _fixo("BBB", course=200.0)]
        segs = validar_segmentos_rota(fixos, 340, {})
        assert segs[0].active_level == 340

    def test_nivel_abaixo_do_minimo_do_segmento(self):
        # Mínimo de 38.000 ft (F380) com nível F350 → erro
        fixos = [_fixo("AAA", altitude_minima=38000), _fixo("BBB", course=100.0)]
        with pytest.raises(NivelAbaixoDoMinimo):
            validar_segmentos_rota(fixos, 350, {})

    def test_aerovia_forward_only_voada_ao_contrario(self):
        fixos = [
            _fixo("AAA", restriction="F"),
            _fixo("BBB", course=100.0, is_reverse=True),
        ]
        with pytest.raises(SentidoProibido):
            validar_segmentos_rota(fixos, 350, {})

    def test_level_map_muda_o_nivel_ativo_do_segmento(self):
        fixos = [_fixo("AAA"), _fixo("BBB", course=200.0)]
        segs = validar_segmentos_rota(fixos, 350, {"AAA": 340})
        assert segs[0].active_level == 340

    def test_rumo_reverso_soma_180_graus(self):
        # Voando a aerovia ao contrário: course de referência 100° vira 280°,
        # que exige nível PAR → F340 válido
        fixos = [
            _fixo("AAA", course=100.0),
            _fixo("BBB", course=100.0, is_reverse=True),
        ]
        segs = validar_segmentos_rota(fixos, 340, {})
        assert segs[0].course == 280.0

    def test_funcao_e_pura_nao_muta_os_fixos_de_entrada(self):
        # Contrato de pureza: validar não pode alterar os objetos recebidos
        fixos = [_fixo("AAA"), _fixo("BBB", course=100.0)]
        copias = [FixoRota(**vars(f)) for f in fixos]
        validar_segmentos_rota(fixos, 350, {})
        assert fixos == copias

    def test_juncao_de_aerovias_usa_dados_da_aerovia_de_saida(self):
        # Rota AAA -UZ1-> BBB -UW2-> CCC: BBB aparece duas vezes (fim da UZ1,
        # início da UW2). O segmento BBB→CCC deve reportar a aerovia de chegada
        # em CCC (UW2), e a restrição de saída de BBB vem do registro da UW2.
        fixos = [
            _fixo("AAA", airway="UZ1"),
            _fixo("BBB", airway="UZ1", course=100.0),
            _fixo("BBB", airway="UW2"),
            _fixo("CCC", airway="UW2", course=90.0),
        ]
        segs = validar_segmentos_rota(fixos, 350, {})
        assert [(s.from_waypoint, s.to_waypoint, s.airway) for s in segs] == [
            ("AAA", "BBB", "UZ1"),
            ("BBB", "CCC", "UW2"),
        ]
