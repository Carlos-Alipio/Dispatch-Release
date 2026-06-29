import sqlite3
from pathlib import Path
from typing import Optional, List
from core_aero.domain.entidades import Aerodromo, AerodromoPrincipal, Coordenada, FixoRota, RegraCruzeiro

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

    def buscar_aerodromos_ifr_hard(self) -> List[AerodromoPrincipal]:
        cursor = self.conexao.cursor()
        cursor.execute("""
            SELECT 
                airport_identifier, 
                airport_name,
                airport_ref_latitude, 
                airport_ref_longitude, 
                elevation 
            FROM tbl_airports 
            WHERE ifr_capability = 'Y' 
              AND longest_runway_surface_code = 'H'
        """)
        
        return [
            AerodromoPrincipal(
                icao=row["airport_identifier"],
                nome=row["airport_name"],
                lat_deg=row["airport_ref_latitude"],
                lon_deg=row["airport_ref_longitude"],
                elevacao_ft=row["elevation"]
            )
            for row in cursor.fetchall()
        ]

    def _clean_wp_name(self, wp: str) -> str:
        return wp.split('/')[0].strip()

    def buscar_coordenadas(self, wp_name: str) -> Optional[Coordenada]:
        wp_clean = self._clean_wp_name(wp_name)
        cursor = self.conexao.cursor()
        
        # 1. Enroute waypoints
        cursor.execute('SELECT waypoint_latitude, waypoint_longitude FROM tbl_enroute_waypoints WHERE waypoint_identifier = ?', (wp_clean,))
        row = cursor.fetchone()
        if row: return Coordenada(row["waypoint_latitude"], row["waypoint_longitude"])

        # 2. Terminal waypoints
        cursor.execute('SELECT waypoint_latitude, waypoint_longitude FROM tbl_terminal_waypoints WHERE waypoint_identifier = ?', (wp_clean,))
        row = cursor.fetchone()
        if row: return Coordenada(row["waypoint_latitude"], row["waypoint_longitude"])
            
        # 3. Airports
        cursor.execute('SELECT airport_ref_latitude, airport_ref_longitude FROM tbl_airports WHERE airport_identifier = ?', (wp_clean,))
        row = cursor.fetchone()
        if row: return Coordenada(row["airport_ref_latitude"], row["airport_ref_longitude"])

        # 4. VORs/NDBs
        cursor.execute('SELECT vor_latitude, vor_longitude FROM tbl_vhfnavaids WHERE vor_identifier = ?', (wp_clean,))
        row = cursor.fetchone()
        if row: return Coordenada(row["vor_latitude"], row["vor_longitude"])

        return None

    def buscar_variacao_magnetica(self, lat: float, lon: float) -> float:
        cursor = self.conexao.cursor()
        cursor.execute('''
            SELECT magnetic_variation FROM tbl_vhfnavaids
            ORDER BY ((vor_latitude - ?) * (vor_latitude - ?)) + ((vor_longitude - ?) * (vor_longitude - ?))
            LIMIT 1
        ''', (lat, lat, lon, lon))
        row = cursor.fetchone()
        if row and row["magnetic_variation"] is not None:
            return row["magnetic_variation"]
        return -22.0

    def buscar_regras_cruzeiro(self, cruise_table_id: str) -> List[RegraCruzeiro]:
        cursor = self.conexao.cursor()
        cursor.execute('''
            SELECT course_from, course_to, cruise_level_from2
            FROM tbl_cruising_tables
            WHERE cruise_table_identifier = ?
        ''', (cruise_table_id,))
        rows = cursor.fetchall()
        return [
            RegraCruzeiro(course_from=r["course_from"], course_to=r["course_to"], cruise_level_from2=r["cruise_level_from2"])
            for r in rows
        ]

    def buscar_fixos_aerovia(self, start_wp: str, airway: str, end_wp: str) -> List[FixoRota]:
        start_wp_clean = self._clean_wp_name(start_wp)
        end_wp_clean = self._clean_wp_name(end_wp)
        
        cursor = self.conexao.cursor()
        cursor.execute(
            'SELECT seqno FROM tbl_enroute_airways WHERE route_identifier = ? AND waypoint_identifier = ?',
            (airway, start_wp_clean)
        )
        start_row = cursor.fetchone()
        cursor.execute(
            'SELECT seqno FROM tbl_enroute_airways WHERE route_identifier = ? AND waypoint_identifier = ?',
            (airway, end_wp_clean)
        )
        end_row = cursor.fetchone()

        if not start_row or not end_row:
            raise ValueError(f"Fixo {start_wp_clean if not start_row else end_wp_clean} nao encontrado na {airway}.")

        start_seq, end_seq = start_row["seqno"], end_row["seqno"]
        is_reverse = start_seq > end_seq

        query = f'''
            SELECT waypoint_identifier, minimum_altitude1, maximum_altitude, inbound_course, direction_restriction, crusing_table_identifier
            FROM tbl_enroute_airways
            WHERE route_identifier = ? AND seqno BETWEEN ? AND ?
            ORDER BY seqno {'DESC' if is_reverse else 'ASC'}
        '''
        cursor.execute(query, (airway, min(start_seq, end_seq), max(start_seq, end_seq)))
        rows = cursor.fetchall()
        
        fixos = []
        for r in rows:
            cruise_table = r["crusing_table_identifier"]
            regras = self.buscar_regras_cruzeiro(cruise_table) if cruise_table else []
            
            fixos.append(FixoRota(
                id=r["waypoint_identifier"],
                is_reverse=is_reverse,
                airway_ref=airway,
                min=r["minimum_altitude1"],
                max=r["maximum_altitude"],
                course=r["inbound_course"],
                restriction=r["direction_restriction"],
                cruise_table=cruise_table,
                regras_cruzeiro=regras
            ))
        return fixos