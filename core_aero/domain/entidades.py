from dataclasses import dataclass, field
from typing import Optional, List

@dataclass
class Aerodromo:
    icao: str
    nome: str
    latitude: float
    longitude: float
    elevacao_ft: int

@dataclass
class AerodromoPrincipal:
    icao: str
    nome: str
    latitude: float
    longitude: float
    elevacao_ft: int

@dataclass
class Coordenada:
    latitude: float
    longitude: float

@dataclass
class RegraCruzeiro:
    course_from: float
    course_to: float
    cruise_level_from2: Optional[int]

@dataclass
class FixoRota:
    id: str
    is_reverse: bool
    airway_ref: str
    course: Optional[float] = None
    # Em pés (ft), como vem do AIRAC. Nomes completos: "min"/"max" sombreariam
    # as funções builtin do Python de mesmo nome.
    altitude_minima: Optional[int] = None
    altitude_maxima: Optional[int] = None
    restriction: Optional[str] = None
    cruise_table: Optional[str] = None
    regras_cruzeiro: List[RegraCruzeiro] = field(default_factory=list)

@dataclass
class SegmentoValidado:
    from_waypoint: str
    to_waypoint: str
    airway: str
    active_level: int
    course: Optional[float] = None
    min_altitude: Optional[int] = None
    max_altitude: Optional[int] = None

@dataclass
class AuxilioNDB:
    identifier: str
    nome: str
    frequencia_khz: float
    latitude: float
    longitude: float

@dataclass
class AuxilioVOR:
    identifier: str
    nome: str
    frequencia_mhz: float
    latitude: float
    longitude: float

@dataclass
class AuxilioFixo:
    identifier: str
    usage: str
    latitude: float
    longitude: float

@dataclass
class AeroviaLinha:
    route_identifier: str
    usage: str          # 'HI' ou 'LO'
    direction: str      # 'ONE-WAY' ou 'TWO-WAY'
    coordenadas: List[List[float]] # Lista de [lon, lat] para o LineString

@dataclass
class AreaRestrita:
    designation: str
    nome: str
    tipo: str  # P, R, D, MOA, etc
    coordenadas: List[List[float]] # Lista de [lon, lat] formando o Polígono

@dataclass
class AreaFir:
    identifier: str
    nome: str
    indicador: str # F para FIR, U para UIR
    coordenadas: List[List[float]]
