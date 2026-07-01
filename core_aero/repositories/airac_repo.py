import sqlite3
from pathlib import Path
from typing import Optional, List
from core_aero.domain.entidades import Aerodromo, AerodromoPrincipal, Coordenada, FixoRota, RegraCruzeiro, AuxilioNDB, AuxilioVOR, AuxilioFixo, AeroviaLinha

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

    def buscar_ndbs_enroute(self) -> List[AuxilioNDB]:
        cursor = self.conexao.cursor()
        
        # Fazemos a consulta pedindo apenas os NDBs que têm coordenada válida
        cursor.execute("""
            SELECT 
                ndb_identifier,
                ndb_name,
                ndb_frequency,
                ndb_latitude,
                ndb_longitude
            FROM tbl_enroute_ndbnavaids
            WHERE ndb_latitude IS NOT NULL 
            AND ndb_longitude IS NOT NULL
        """)
        
        # Lei II: Nunca retorne o dado cru do banco. 
        # Nós pegamos cada linha e "vestimos" com a roupa do Domínio (AuxilioNDB).
        return [
            AuxilioNDB(
                identifier=row["ndb_identifier"],
                nome=row["ndb_name"] if row["ndb_name"] else "",
                frequencia_khz=row["ndb_frequency"],
                lat_deg=row["ndb_latitude"],
                lon_deg=row["ndb_longitude"]
            )
            for row in cursor.fetchall()
        ]

    def buscar_vors(self) -> List[AuxilioVOR]:
        cursor = self.conexao.cursor()
        
        # Fazemos a consulta pedindo apenas os VORs que têm coordenada válida
        cursor.execute("""
            SELECT 
                vor_identifier,
                vor_name,
                vor_frequency,
                vor_latitude,
                vor_longitude
            FROM tbl_vhfnavaids
            WHERE vor_latitude IS NOT NULL 
            AND vor_longitude IS NOT NULL
        """)
        
        # Lei II: Nunca retorne o dado cru do banco. 
        # Nós pegamos cada linha e "vestimos" com a roupa do Domínio (AuxilioNDB).
        return [
            AuxilioVOR(
                identifier=row["vor_identifier"],
                nome=row["vor_name"] if row["vor_name"] else "",
                frequencia_mhz=row["vor_frequency"],
                lat_deg=row["vor_latitude"],
                lon_deg=row["vor_longitude"]
            )
            for row in cursor.fetchall()
        ]

    def buscar_fixos_mapa(self) -> List[AuxilioFixo]:
        cursor = self.conexao.cursor()
        
        cursor.execute("""
            SELECT 
                waypoint_identifier,
                waypoint_usage,
                waypoint_latitude,
                waypoint_longitude
            FROM tbl_enroute_waypoints
            WHERE waypoint_latitude IS NOT NULL 
            AND waypoint_longitude IS NOT NULL
        """)
        
        return [
            AuxilioFixo(
                identifier=row["waypoint_identifier"],
                usage=row["waypoint_usage"] if row["waypoint_usage"] else "",
                lat_deg=row["waypoint_latitude"],
                lon_deg=row["waypoint_longitude"]
            )
            for row in cursor.fetchall()
        ]

    def buscar_linhas_aerovias(self) -> List[AeroviaLinha]:
        cursor = self.conexao.cursor()
        
        cursor.execute("""
            SELECT 
                route_identifier,
                flightlevel,
                direction_restriction,
                waypoint_latitude,
                waypoint_longitude
            FROM tbl_enroute_airways
            WHERE waypoint_latitude IS NOT NULL 
              AND waypoint_longitude IS NOT NULL
            ORDER BY route_identifier, seqno ASC
        """)
        
        linhas = []
        current_route = None
        current_coords = []
        current_usage = 'BOTH'
        current_direction = 'TWO-WAY'
        
        for row in cursor.fetchall():
            route = row["route_identifier"]
            lat = row["waypoint_latitude"]
            lon = row["waypoint_longitude"]
            fl = row["flightlevel"]
            d_res = row["direction_restriction"]
            
            # Simplificando H -> HI, L -> LO, B -> BOTH
            usage = 'HI' if fl == 'H' else 'LO' if fl == 'L' else 'BOTH'
            direction = 'ONE-WAY' if d_res in ('F', 'B') else 'TWO-WAY'
            
            if route != current_route:
                if current_route is not None and len(current_coords) > 1:
                    linhas.append(AeroviaLinha(
                        route_identifier=current_route,
                        usage=current_usage,
                        direction=current_direction,
                        coordenadas=current_coords
                    ))
                current_route = route
                current_coords = []
                current_usage = usage
                current_direction = direction
                
            current_coords.append([lon, lat])
            
        if current_route is not None and len(current_coords) > 1:
            linhas.append(AeroviaLinha(
                route_identifier=current_route,
                usage=current_usage,
                direction=current_direction,
                coordenadas=current_coords
            ))
            
        return linhas