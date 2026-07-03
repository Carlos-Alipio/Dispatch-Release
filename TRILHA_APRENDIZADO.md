# Dispatch-Release — Análise da Aplicação e Trilha de Aprendizado

> Documento gerado a partir da análise do código em julho/2026. Serve como mapa de estudo
> para dominar todas as tecnologias, bibliotecas e práticas envolvidas na criação desta aplicação.

---

## Parte 1 — Análise da Aplicação

### 1.1 O que é o Dispatch-Release

Um **cockpit web de despacho operacional de voo**: uma ferramenta para despachantes/planejadores
que permite planejar rotas IFR sobre dados AIRAC reais e visualizar a infraestrutura de
navegação aérea em um mapa interativo. Funcionalidades atuais:

- Planejamento de rota por string aeronáutica (ex.: `OBLAX UZ21 VUNOX`), com resolução
  da sequência de fixos ao longo das aerovias.
- Validação de níveis de cruzeiro contra a **regra semicircular** e restrições
  de altitude mínima/máxima por segmento.
- Cálculo de distância ortodrômica (Haversine), rumo verdadeiro e **rumo magnético**
  (com variação magnética consultada no banco AIRAC).
- Visualização em mapa: aeródromos IFR, VOR, NDB, fixos, aerovias (HI/LO),
  áreas restritas/proibidas/perigosas, FIR/UIR e camada de precipitação em tempo
  real do OpenWeatherMap.

### 1.2 Arquitetura

O projeto segue **Clean Architecture** em 4 camadas, com dependências apontando sempre
"para dentro" (a camada de domínio não conhece Django nem SQLite):

```
┌────────────────────────────────────────────────────────────┐
│ APRESENTAÇÃO — core_aero/templates/template.html           │
│ MapLibre GL JS + TailwindCSS + JavaScript puro (fetch)     │
└────────────────────────────────────────────────────────────┘
                        ↑ HTTP / GeoJSON ↓
┌────────────────────────────────────────────────────────────┐
│ API — core_aero/api.py (Django Ninja + Pydantic)           │
│ /api/rotas/*, /api/v1/geo/airac/* → serializa em GeoJSON   │
└────────────────────────────────────────────────────────────┘
                        ↑ chamadas ↓
┌────────────────────────────────────────────────────────────┐
│ DOMÍNIO — core_aero/domain/                                │
│ entidades.py (dataclasses) + planejamento.py (funções      │
│ puras: parsing de rota, validação, Haversine, rumos)       │
└────────────────────────────────────────────────────────────┘
                        ↑ objetos de domínio ↓
┌────────────────────────────────────────────────────────────┐
│ REPOSITÓRIO — core_aero/repositories/airac_repo.py         │
│ SQLite AIRAC (173 MB, aberto em modo read-only)            │
└────────────────────────────────────────────────────────────┘
```

**Fluxo de dados de uma rota:**

1. O usuário digita a rota no formulário do cockpit → `fetch()` chama
   `GET /api/rotas/geojson_completo/`.
2. `extrair_instrucoes_rota()` (domínio) converte a string em triplas
   `(fixo_inicial, aerovia, fixo_final)`.
3. `AiracRepository.buscar_fixos_aerovia()` consulta o SQLite e devolve a sequência
   de fixos (detectando o sentido da aerovia pelo `seqno`).
4. `validar_segmentos_rota()` aplica a regra semicircular e restrições de altitude;
   `calcular_distancia_e_rumo()` e `calcular_rumo_magnetico()` computam a navegação.
5. A API serializa tudo em **GeoJSON (RFC 7946)** — Points para fixos, LineString
   para a rota — e o MapLibre GL renderiza como sources/layers no mapa.

### 1.3 Inventário de tecnologias (papel neste projeto)

| Tecnologia | Versão | Papel no projeto |
|---|---|---|
| Python | 3.14 | Linguagem do backend |
| Django | 6.0.6 | Framework web: settings, URLs, servidor de dev, templates |
| Django Ninja | 1.6.2 | Framework REST: decorators de endpoint, integração Pydantic |
| Pydantic | 2.x | Schemas de validação de entrada/saída da API |
| SQLite | 3 | Banco AIRAC estático (`core_aero/data/airac/airac_atual.s3db`, modo `?mode=ro`) |
| MapLibre GL JS | 4.1.3 | Mapa WebGL: sources, layers, filtros, ícones SVG |
| TailwindCSS | 4 (CDN) | Estilização utility-first do cockpit |
| JavaScript (ES6+) | — | Lógica do frontend: `fetch`, async/await, manipulação de camadas |
| GeoJSON | RFC 7946 | Formato de troca API → mapa (atenção: ordem `[lon, lat]`) |
| OpenWeatherMap | tiles | Camada raster de precipitação em tempo real |
| CartoDB Positron | style | Mapa-base (style JSON público) |

### 1.4 Pontos fortes do código atual

- **Separação de camadas real**: `domain/planejamento.py` são funções puras, sem
  nenhum import de Django ou SQLite — testáveis isoladamente.
- **Entidades como `@dataclass`** (`Aerodromo`, `FixoRota`, `SegmentoValidado`, ...),
  sem acoplamento ao ORM.
- **Padrão Repository**: toda consulta ao AIRAC passa por `AiracRepository`, com o
  banco aberto em modo somente-leitura (protege o ciclo AIRAC).
- **Type hints em todo o backend** e schemas Pydantic na borda da API.
- **Cache HTTP consciente do domínio**: dados AIRAC estáticos com `max-age` de 28 dias
  (a duração de um ciclo AIRAC).

### 1.5 Lacunas (que a trilha aborda no Módulo 8)

> **Atualização (jul/2026):** todas as lacunas abaixo foram corrigidas no próprio repo —
> estude as correções como material do Módulo 8. A tabela original fica como registro.

| Lacuna | Onde | Correção aplicada |
|---|---|---|
| Nenhum teste automatizado | projeto inteiro | Suíte pytest em `core_aero/tests/` (41 testes) |
| Chave OpenWeatherMap hardcoded | `template.html` | Injetada via `.env` → `settings.OWM_API_KEY` → template (revogue a chave antiga!) |
| `DEBUG=True` e `SECRET_KEY` no código | `aero_saas/settings.py` | Variáveis de ambiente com `python-dotenv` (`.env.example` documenta) |
| Sem logging estruturado | backend | `LOGGING` no settings + loggers em `api.py` e `airac_repo.py` |
| Erros genéricos (`ValueError`) | domínio/API | Hierarquia em `core_aero/domain/excecoes.py` + exception handlers (404/422/503) |
| Dependências não usadas (folium, requests, numpy) | `requirements.txt` | Requirements curado + `requirements-dev.txt` |
| Sem Docker/CI | raiz | `Dockerfile` (gunicorn) + `.github/workflows/ci.yml` (pytest) |
| Commits com mensagem vazia (".") | histórico git | `.gitmessage` + `CONTRIBUTING.md` (histórico antigo preservado — reescrever seria destrutivo) |

---

## Parte 2 — Trilha de Aprendizado

A trilha está organizada em **8 módulos progressivos**. Cada módulo indica o que estudar,
**onde aquilo aparece neste projeto** (a melhor forma de fixar é reler o próprio código
depois de estudar o conceito) e um exercício prático.

Estimativa total: **4 a 8 meses** com dedicação parcial (10–15 h/semana), dependendo
da base inicial. Os módulos 1–3 são sequenciais; 4–6 podem ser intercalados; 7–8
consolidam tudo.

### Módulo 1 — Fundamentos de Python moderno (3–5 semanas)

**O que estudar:**
- Sintaxe, estruturas de dados (list, dict, tuple, set), funções, compreensões.
- **Type hints**: `List`, `Dict`, `Optional`, `Tuple`, tipos de retorno.
- **Dataclasses** (`@dataclass`): quando usar em vez de dicts ou classes comuns.
- Módulos e pacotes (`__init__.py`), imports absolutos/relativos.
- Ambientes virtuais (`venv`), `pip`, `requirements.txt`.
- `math` (trigonometria: `radians`, `sin`, `cos`, `atan2`) e expressões regulares (`re`).

**No projeto:**
- `core_aero/domain/entidades.py` — 12 dataclasses puras.
- `core_aero/domain/planejamento.py` — funções tipadas com tuplas aninhadas no retorno,
  ex.: `extrair_instrucoes_rota(...) -> Tuple[List[Tuple[str, str, str]], Dict[str, int]]`.

**Exercício:** reescreva `Coordenada` e `Aerodromo` do zero e crie uma função tipada
que converta graus decimais em graus/minutos/segundos.

**Recursos:** documentação oficial do Python (tutorial), "Python Fluente" (Luciano Ramalho),
[docs.python.org/pt-br](https://docs.python.org/pt-br/3/).

### Módulo 2 — SQL e SQLite (2–3 semanas)

**O que estudar:**
- SELECT, WHERE, ORDER BY, JOIN, índices, agregações.
- `sqlite3` no Python: conexões, cursores, parâmetros (`?` — nunca f-strings em SQL),
  `row_factory`.
- Abertura por URI e **modo read-only** (`file:...?mode=ro`).
- Como explorar um banco desconhecido: `.tables`, `.schema`, `PRAGMA table_info`.

**No projeto:**
- `core_aero/repositories/airac_repo.py` — 519 linhas de consultas ao banco AIRAC:
  `buscar_fixos_aerovia()` ordena por `seqno` e detecta o sentido da aerovia;
  `buscar_areas_restritas()` reconstrói polígonos (incluindo círculos gerados
  por `_gerar_circulo()`).
- Banco real para praticar: `core_aero/data/airac/airac_atual.s3db`
  (tabelas `tbl_enroute_airways`, `tbl_vhfnavaids`, `tbl_fir_uir`, etc.).

**Exercício:** abra o `.s3db` no terminal com `sqlite3` e escreva uma query que liste
todos os VORs do Brasil com frequência e coordenadas. Depois compare com `buscar_vors()`.

### Módulo 3 — HTTP, APIs REST e o backend Django (4–6 semanas)

**O que estudar:**
- HTTP: verbos, códigos de status, headers, **cache (`Cache-Control`, `max-age`)**, JSON.
- Django: estrutura de projeto (`manage.py`, `settings.py`, `urls.py`), apps,
  templates, arquivos estáticos, WSGI vs ASGI (visão geral).
- **Django Ninja**: decorators (`@api.get`), path/query params, `response=Schema`.
- **Pydantic 2**: `Schema`/`BaseModel`, validação automática, serialização.

**No projeto:**
- `aero_saas/settings.py` e `aero_saas/urls.py` — configuração mínima do Django.
- `core_aero/api.py` — 10 endpoints; observe como `calcular_rota_geojson_completo()`
  recebe query params (`route_string`, `initial_level`) e como os endpoints
  `/v1/geo/airac/*` setam cache de 28 dias no `HttpResponse`.

**Exercício:** adicione um endpoint `GET /api/v1/geo/airac/aerodromos/{icao}/vizinhos`
que retorne aeródromos num raio de N milhas náuticas, com schema Pydantic próprio.

**Recursos:** documentação do Django ([docs.djangoproject.com](https://docs.djangoproject.com)),
[django-ninja.dev](https://django-ninja.dev), [docs.pydantic.dev](https://docs.pydantic.dev).

### Módulo 4 — Frontend: HTML, CSS e JavaScript (3–5 semanas)

**O que estudar:**
- HTML semântico e DOM (`querySelector`, eventos, criação de elementos).
- JavaScript moderno: `const/let`, arrow functions, template literals,
  **Promises e `async/await`**, `fetch()`, JSON.
- **TailwindCSS**: filosofia utility-first, classes de layout (flex/grid), estados.
- Padrões de UI sem framework: estado em variáveis, funções de render, toggles de camada.

**No projeto:**
- `core_aero/templates/template.html` — 726 linhas: formulário de rota, botões de
  filtro HI/LO/BOTH de aerovias, toggles de camadas, tudo em JS puro com `fetch`
  para a API.

**Exercício:** adicione um botão que mostre/oculte a camada de FIRs e persista a
escolha em `localStorage`.

**Recursos:** [MDN Web Docs](https://developer.mozilla.org/pt-BR/) (referência principal),
[tailwindcss.com/docs](https://tailwindcss.com/docs).

### Módulo 5 — Cartografia web: GeoJSON e MapLibre GL (3–4 semanas)

**O que estudar:**
- **GeoJSON (RFC 7946)**: Feature, FeatureCollection, Point, LineString, Polygon;
  a pegadinha clássica da ordem **`[longitude, latitude]`**; orientação anti-horária
  de anéis de polígono (veja `_ensure_ccw()` no repositório).
- **MapLibre GL JS**: `Map`, styles, **sources** (geojson, raster) e **layers**
  (circle, line, fill, symbol), expressões de filtro, `map.addImage()` para ícones SVG,
  `LngLatBounds`/`fitBounds`, popups e eventos de clique.
- Tiles raster e o esquema `{z}/{x}/{y}` (usado na camada do OpenWeatherMap).
- Projeções: Web Mercator vs coordenadas geográficas (noção).

**No projeto:**
- Toda a serialização GeoJSON em `core_aero/api.py`.
- Em `template.html`: criação do mapa com style do CartoDB Positron, source raster
  do OpenWeatherMap (`tile.openweathermap.org/map/precipitation_new/{z}/{x}/{y}.png`),
  ícones SVG em `core_aero/static/core_aero/img/` (símbolos VOR/NDB/fixo/seta).

**Exercício:** crie uma camada nova que pinte cada FIR com uma cor diferente e mostre
o nome num popup ao clicar.

**Recursos:** [maplibre.org/maplibre-gl-js/docs](https://maplibre.org/maplibre-gl-js/docs/),
especificação GeoJSON ([RFC 7946](https://datatracker.ietf.org/doc/html/rfc7946)).

### Módulo 6 — Matemática de navegação e domínio aeronáutico (2–4 semanas)

**O que estudar:**
- **Fórmula de Haversine** (distância ortodrômica sobre a esfera) e cálculo do
  **rumo verdadeiro inicial** com `atan2`.
- **Variação magnética**: rumo magnético = rumo verdadeiro − variação.
- **Regra semicircular**: níveis ímpares/pares conforme o rumo magnético
  (000–179° / 180–359°), e como tabelas de cruzeiro do AIRAC a codificam.
- Domínio aeronáutico: ciclo **AIRAC de 28 dias**, aerovias (HI/LO), fixos e
  auxílios (VOR/NDB), FIR/UIR, classificação de áreas P/R/D (proibida/restrita/perigosa),
  níveis de voo (FL = altitude/100 ft), milha náutica.

**No projeto:**
- `calcular_distancia_e_rumo()` e `calcular_rumo_magnetico()` em
  `core_aero/domain/planejamento.py` — implementação direta de Haversine e rumos.
- `is_course_odd()` + `validar_segmentos_rota()` — a regra semicircular em código.
- `buscar_variacao_magnetica()` em `airac_repo.py` — variação vinda do banco AIRAC.

**Exercício:** reimplemente `calcular_distancia_e_rumo()` do zero, sem olhar o original,
e compare os resultados para 5 pares de aeródromos conhecidos (ex.: SBGR→SBGL).

**Recursos:** [Movable Type — Calculating distance/bearing](https://www.movable-type.co.uk/scripts/latlong.html)
(referência clássica das fórmulas), ICAO Annex 2 (regra semicircular), documentação ARINC 424.

### Módulo 7 — Arquitetura de software (2–3 semanas)

**O que estudar:**
- **Clean Architecture / Arquitetura Hexagonal**: regra de dependência (domínio no
  centro), fronteiras entre camadas.
- **Padrão Repository**: abstrair o acesso a dados atrás de uma interface que devolve
  objetos de domínio.
- **Funções puras** e por que elas são o alvo mais fácil (e valioso) de teste.
- Trade-offs: quando essa separação vale a pena vs quando é burocracia.

**No projeto (este projeto É o estudo de caso):**
- Note que `domain/` não importa Django nem sqlite3 — abra os imports e confira.
- `AiracRepository` devolve dataclasses (`FixoRota`, `AreaFir`), nunca rows crus.
- A API é a única camada que conhece HTTP e GeoJSON; o domínio não sabe que existe web.
- O arquivo `SYSTEM_PROMPT.md` na raiz documenta as regras de arquitetura do projeto.

**Exercício:** desenhe (papel mesmo) o diagrama de dependências entre os módulos do
projeto e verifique que nenhuma seta aponta "para fora" do domínio.

**Recursos:** "Clean Architecture" (Robert C. Martin), "Architecture Patterns with Python"
(Percival & Gregory — gratuito em [cosmicpython.com](https://www.cosmicpython.com)).

### Módulo 8 — Boas práticas e profissionalização (4–6 semanas, aplicado a este repo)

Este módulo transforma as lacunas reais do projeto em exercícios. Ordem sugerida:

1. **Testes (a maior prioridade)** — pytest.
   - Comece pelas funções puras: `extrair_instrucoes_rota`, `is_course_odd`,
     `calcular_distancia_e_rumo` (elas não precisam de banco nem de Django).
   - Depois, testes do repositório contra um SQLite pequeno de fixture.
   - Por fim, testes de endpoint com o `TestClient` do Django Ninja.
   - Conceitos: arrange/act/assert, fixtures, parametrização, casos de borda
     (rota vazia, aerovia inexistente, antípodas no Haversine).

2. **Segredos e configuração** — variáveis de ambiente.
   - Mover `SECRET_KEY`, `DEBUG` e a chave do OpenWeatherMap para um `.env`
     (`django-environ` ou `os.environ`), adicionar `.env` ao `.gitignore`
     e **revogar/regenerar a chave OWM exposta**.
   - A chave do frontend pode ser injetada no template pelo backend.

3. **Tratamento de erros e logging.**
   - Exceções customizadas no domínio (ex.: `AeroviaNaoEncontrada`,
     `NivelInvalido`) mapeadas para respostas HTTP 404/422 na API.
   - Módulo `logging` do Python com configuração no `settings.py`.

4. **Higiene de dependências.**
   - Remover folium/branca/requests/numpy do `requirements.txt` (não são usados)
     e fixar versões. Conhecer `pip freeze` vs arquivo curado; opcional: `uv` ou `pip-tools`.

5. **Git profissional.**
   - Mensagens no padrão Conventional Commits (`feat:`, `fix:`, `refactor:` — os
     commits recentes do projeto já seguem isso; os antigos "." mostram o contraste).
   - Branches, PRs e revisão de código, mesmo trabalhando sozinho.

6. **Docker e CI (introdução).**
   - Dockerfile simples para o app; GitHub Actions rodando os testes a cada push.

7. **Deploy (visão geral).**
   - `DEBUG=False`, `ALLOWED_HOSTS`, servir estáticos (whitenoise), gunicorn/uvicorn.

**Recursos:** [docs.pytest.org](https://docs.pytest.org), "Boas práticas" do
[12factor.net/pt_br](https://12factor.net/pt_br/), [conventionalcommits.org](https://www.conventionalcommits.org/pt-br/),
documentação do GitHub Actions.

---

## Sequência resumida

| Fase | Módulos | Marco de conclusão |
|---|---|---|
| Base | 1, 2 | Ler `planejamento.py` e `airac_repo.py` inteiros e entender cada linha |
| Backend | 3 | Criar um endpoint novo funcional na API |
| Frontend + Mapa | 4, 5 | Adicionar uma camada nova ao cockpit de ponta a ponta |
| Domínio | 6 | Reimplementar Haversine/rumos e validar contra o original |
| Consolidação | 7, 8 | Suíte de testes rodando em CI, segredos fora do código |

**Princípio geral da trilha:** estude o conceito → encontre-o neste código →
modifique algo pequeno → quebre e conserte. Este repositório é pequeno o bastante
(~2.000 linhas) para ser lido por completo, e real o bastante para ensinar o processo
inteiro de criação de uma aplicação web geoespacial.
