import sqlite3
from pathlib import Path

class AiracRepository:
    def __init__(self, ciclo: str):
        # Monta o caminho dinâmico para o arquivo: core_aero/data/airac/airac_2606.s3db
        caminho_db = Path(f"core_aero/data/airac/airac_{ciclo}.s3db")

        if not caminho_db.exists():
            raise FileNotFoundError(f"Banco de dados do ciclo {ciclo} não encontrado!")
        # Conecta em modo "Read-Only" (URI). 
        # Impede que o seu código acidentalmente apague um VOR do banco.
        self.conexao = sqlite3.connect(f"file:{caminho_db}?mode=ro", uri=True)
        # Configura para retornar as colunas como dicionários
        self.conexao.row_factory = sqlite3.Row 

    def buscar_aerodromo(self, icao: str) -> dict:
        """Busca o aeródromo e devolve um dicionário (biblioteca) com todos os campos."""
        cursor = self.conexao.cursor()
        
        cursor.execute("""
            SELECT * 
            FROM tbl_airports 
            WHERE airport_identifier = ?
        """, (icao.upper(),))

        linha = cursor.fetchone()
        if not linha:
            raise ValueError(f"Aeródromo {icao} não encontrado no ciclo atual.")
            
        return dict(linha)