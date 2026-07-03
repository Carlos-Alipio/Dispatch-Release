"""
Exceções de domínio do planejamento de voo.

A hierarquia permite que a camada de API mapeie cada família de erro para um
status HTTP adequado sem inspecionar mensagens de texto:

    ErroDominio                  -> 500 (falha inesperada de regra de negócio)
    ├── BaseAiracIndisponivel    -> 503 (banco AIRAC ausente/corrompido)
    ├── RecursoNaoEncontrado     -> 404
    │   ├── AerodromoNaoEncontrado
    │   └── FixoNaoEncontrado
    └── RotaInvalida             -> 422 (rota bem formada, mas viola regras)
        ├── SentidoProibido
        ├── NivelAbaixoDoMinimo
        └── NivelInvalidoParaRumo
"""


class ErroDominio(Exception):
    """Base de todas as exceções de negócio do core_aero."""


class BaseAiracIndisponivel(ErroDominio):
    """O arquivo do ciclo AIRAC não foi encontrado ou não pôde ser aberto."""


class RecursoNaoEncontrado(ErroDominio):
    """Um identificador consultado não existe no ciclo AIRAC."""


class AerodromoNaoEncontrado(RecursoNaoEncontrado):
    """ICAO de aeródromo inexistente na tbl_airports."""


class FixoNaoEncontrado(RecursoNaoEncontrado):
    """Fixo/waypoint inexistente, ou não pertencente à aerovia informada."""


class RotaInvalida(ErroDominio):
    """A rota é sintaticamente válida, mas viola regras operacionais."""


class SentidoProibido(RotaInvalida):
    """Tentativa de voar uma aerovia one-way no sentido contrário."""


class NivelAbaixoDoMinimo(RotaInvalida):
    """Nível de cruzeiro abaixo da altitude mínima do segmento (MEA)."""


class NivelInvalidoParaRumo(RotaInvalida):
    """Nível ímpar/par incompatível com o rumo magnético (regra semicircular)."""
