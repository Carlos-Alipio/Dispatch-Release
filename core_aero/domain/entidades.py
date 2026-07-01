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
    lat_deg: float
    lon_deg: float
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
    active_level: Optional[int] = None
    course: Optional[float] = None
    min: Optional[int] = None
    max: Optional[int] = None
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
    lat_deg: float
    lon_deg: float

@dataclass
class AuxilioVOR:
    identifier: str
    nome: str
    frequencia_mhz: float
    lat_deg: float
    lon_deg: float
