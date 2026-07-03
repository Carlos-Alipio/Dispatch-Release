"""
Testes da camada de API (Django Ninja) e da página do Cockpit.

Usam o test client do Django; o repositório é substituído por fakes via
monkeypatch, então não dependem do banco AIRAC.
"""
from core_aero import api as api_module
from core_aero.domain.excecoes import AerodromoNaoEncontrado, BaseAiracIndisponivel


class TestCockpitUi:
    def test_ui_responde_200_na_raiz(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "cockpit.js" in resp.content.decode()

    def test_url_antiga_redireciona_para_a_raiz(self, client):
        resp = client.get("/api/rotas/ui/")
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/"

    def test_chave_owm_vem_das_settings_via_config_bridge(self, client, settings):
        settings.OWM_API_KEY = "CHAVE-DE-TESTE"
        html = client.get("/").content.decode()
        assert "window.COCKPIT_CONFIG" in html
        assert 'owmApiKey: "CHAVE-DE-TESTE"' in html

    def test_nenhuma_chave_hardcoded_no_html(self, client, settings):
        settings.OWM_API_KEY = "CHAVE-DE-TESTE"
        html = client.get("/").content.decode()
        assert "7967a64f1dd8c483f54a358e3ab15961" not in html


class TestMapeamentoDeExcecoes:
    def test_aerodromo_inexistente_vira_404(self, client, monkeypatch):
        class FakeRepo:
            def __init__(self, ciclo="atual"):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def buscar_aerodromo(self, icao):
                raise AerodromoNaoEncontrado(f"Aeródromo {icao} não encontrado.")

        monkeypatch.setattr(api_module, "AiracRepository", FakeRepo)
        resp = client.get("/api/v1/aerodromos/XXXX")
        assert resp.status_code == 404
        assert "erro" in resp.json()

    def test_banco_airac_ausente_vira_503(self, client, monkeypatch):
        class RepoSemBanco:
            def __init__(self, ciclo="atual"):
                raise BaseAiracIndisponivel("Arquivo AIRAC não encontrado.")

        monkeypatch.setattr(api_module, "AiracRepository", RepoSemBanco)
        resp = client.get("/api/v1/aerodromos/SBGR")
        assert resp.status_code == 503
        assert "erro" in resp.json()
