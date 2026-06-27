from dataclasses import dataclass

# O Molde Matemático
@dataclass
class Aerodromo:
    icao: str
    nome: str
    latitude: float
    longitude: float
    elevacao_ft: int