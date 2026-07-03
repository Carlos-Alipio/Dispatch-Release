"""
Testes de integração do repositório AIRAC.

Dependem do arquivo core_aero/data/airac/airac_atual.s3db (173 MB, fora do git);
são pulados automaticamente onde ele não existe (ex.: CI).
"""
from pathlib import Path

import pytest

from core_aero.domain.excecoes import AerodromoNaoEncontrado
from core_aero.repositories.airac_repo import AiracRepository, DATA_DIR

DB_PATH = DATA_DIR / "airac_atual.s3db"

pytestmark = pytest.mark.skipif(
    not DB_PATH.exists(),
    reason="Banco AIRAC não disponível neste ambiente.",
)


@pytest.fixture
def repo() -> AiracRepository:
    return AiracRepository(ciclo="atual")


class TestBuscarAerodromo:
    def test_sbgr_existe_com_coordenadas_plausiveis(self, repo):
        aero = repo.buscar_aerodromo("SBGR")
        assert aero.icao == "SBGR"
        assert -24.0 < aero.latitude < -23.0
        assert -47.0 < aero.longitude < -46.0

    def test_icao_minusculo_e_normalizado(self, repo):
        assert repo.buscar_aerodromo("sbgr").icao == "SBGR"

    def test_icao_inexistente_levanta_excecao_de_dominio(self, repo):
        with pytest.raises(AerodromoNaoEncontrado):
            repo.buscar_aerodromo("ZZZZ")


class TestBuscarCoordenadas:
    def test_fixo_inexistente_retorna_none(self, repo):
        assert repo.buscar_coordenadas("XXXXXXX") is None

    def test_aerodromo_tambem_resolve_como_coordenada(self, repo):
        coord = repo.buscar_coordenadas("SBGR")
        assert coord is not None
        assert -24.0 < coord.latitude < -23.0
