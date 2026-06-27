import sqlite3
from pathlib import Path
from core_aero.domain.entidades import Aerodromo

class AiracRepository:
    def __init__(self, ciclo: str = "atual"):
        # Aponta para o arquivo: core_aero/data/airac/airac_atual.s3db
        caminho_db = Path(f"core_aero/data/airac/airac_{ciclo}.s3db")
        
        if not caminho_db.exists():
            raise FileNotFoundError(f"Arquivo AIRAC não encontrado: {caminho_db}")
            
        # Conexão em modo Read-Only para proteger o banco original
        self.conexao = sqlite3.connect(f"file:{caminho_db}?mode=ro", uri=True)
        self.conexao.row_factory = sqlite3.Row 

    def buscar_aerodromo(self, icao: str) -> Aerodromo:
        cursor = self.conexao.cursor()
        
        # Usando os campos exatos da sua tabela tbl_airports
        cursor.execute("""
            SELECT 
                airport_identifier, 
                airport_name,
                airport_ref_latitude, 
                airport_ref_longitude, 
                elevation 
            FROM tbl_airports 
            WHERE airport_identifier = ?
        """, (icao.upper(),))
        
        linha = cursor.fetchone()
        if not linha:
            raise ValueError(f"Aeródromo {icao} não encontrado no ciclo AIRAC atual.")
            
        return Aerodromo(
            icao=linha["airport_identifier"],
            nome=linha["airport_name"],
            latitude=linha["airport_ref_latitude"],
            longitude=linha["airport_ref_longitude"],
            elevacao_ft=linha["elevation"]
        )