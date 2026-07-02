import sqlite3
from pathlib import Path
from typing import Optional, List
from core_aero.domain.entidades import Aerodromo, AerodromoPrincipal, Coordenada, FixoRota, RegraCruzeiro, AuxilioNDB, AuxilioVOR, AuxilioFixo, AeroviaLinha, AreaRestrita, AreaFir
import math

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

    def _gerar_circulo(self, lat: float, lon: float, radius_nm: float, num_points: int = 36) -> List[List[float]]:
        # Earth radius in NM is ~3440.065
        earth_radius_nm = 3440.065
        coords = []
        lat_rad = math.radians(lat)
        lon_rad = math.radians(lon)
        d_rad = radius_nm / earth_radius_nm

        for i in range(num_points):
            bearing = math.radians(float(i * 360 / num_points))
            lat_point = math.asin(math.sin(lat_rad) * math.cos(d_rad) + 
                                  math.cos(lat_rad) * math.sin(d_rad) * math.cos(bearing))
            lon_point = lon_rad + math.atan2(math.sin(bearing) * math.sin(d_rad) * math.cos(lat_rad), 
                                             math.cos(d_rad) - math.sin(lat_rad) * math.sin(lat_point))
            coords.append([math.degrees(lon_point), math.degrees(lat_point)])
        
        # Close the polygon
        coords.append(coords[0])
        return coords

    def _ensure_ccw(self, coords: List[List[float]]) -> List[List[float]]:
        area = 0.0
        for i in range(len(coords) - 1):
            x1, y1 = coords[i]
            x2, y2 = coords[i+1]
            area += (x1 * y2 - x2 * y1)
        if area < 0:
            return coords[::-1]
        return coords

    def buscar_areas_restritas(self) -> List[AreaRestrita]:
        cursor = self.conexao.cursor()
        
        # O banco de dados mantem a sequência de bordas na ordem de inserção (rowid).
        # Agrupar por nomes que se repetem embaralha tudo. Devemos ler ordenado por rowid.
        # Filtramos apenas os tipos solicitados: D, R, P.
        cursor.execute("""
            SELECT 
                restrictive_airspace_designation,
                restrictive_airspace_name,
                restrictive_type,
                seqno,
                boundary_via,
                latitude,
                longitude,
                arc_origin_latitude,
                arc_origin_longitude,
                arc_distance,
                area_code,
                icao_code,
                multiple_code
            FROM tbl_restrictive_airspace
            WHERE restrictive_type IN ('D', 'R', 'P')
            ORDER BY rowid ASC
        """)
        
        areas = []
        current_id = None
        current_name = ""
        current_type = ""
        current_coords = []
        prev_seqno = 99999
        
        def safe_append_area():
            if current_id is not None and len(current_coords) > 2:
                if current_coords[0] != current_coords[-1]:
                    current_coords.append(current_coords[0])
                
                # Garantir que a geometria está no sentido anti-horário (Counter-Clockwise)
                # O padrão GeoJSON exige CCW para anéis externos. Sentido horário preenche o globo inteiro.
                fixed_coords = self._ensure_ccw(current_coords)
                
                areas.append(AreaRestrita(
                    designation=current_id,
                    nome=current_name,
                    tipo=current_type,
                    coordenadas=[fixed_coords]
                ))

        for row in cursor.fetchall():
            seqno = row["seqno"]
            area_code = row["area_code"] or ""
            icao_code = row["icao_code"] or ""
            desig = row["restrictive_airspace_designation"] or ""
            mult = row["multiple_code"] or ""
            r_name = row["restrictive_airspace_name"] or ""
            r_type = row["restrictive_type"] or ""
            
            area_id = f"{area_code}_{icao_code}_{desig}_{mult}"
            
            # Se o seqno for menor ou igual ao anterior, ou se mudou o ID da área
            if seqno <= prev_seqno or area_id != current_id:
                safe_append_area()
                current_id = area_id
                
                # Nomenclatura: icaocode + restrictive type + "-" designation + " " name
                nome_formatado = f"{icao_code}{r_type}-{desig}"
                if r_name:
                    nome_formatado += f" {r_name}"
                    
                current_name = nome_formatado
                current_type = r_type
                current_coords = []
                
            prev_seqno = seqno
            
            b_via = row["boundary_via"]
            lat = row["latitude"]
            lon = row["longitude"]
            arc_lat = row["arc_origin_latitude"]
            arc_lon = row["arc_origin_longitude"]
            arc_dist = row["arc_distance"]
            
            if b_via in ('C', 'CE') and arc_lat is not None and arc_lon is not None and arc_dist is not None:
                circle_coords = self._gerar_circulo(arc_lat, arc_lon, arc_dist)
                current_coords.extend(circle_coords)
            elif lat is not None and lon is not None:
                current_coords.append([lon, lat])
                
        safe_append_area()
            
        return areas

    def buscar_firs(self) -> List[AreaFir]:
        cursor = self.conexao.cursor()
        
        cursor.execute("""
            SELECT 
                fir_uir_identifier,
                fir_uir_name,
                fir_uir_indicator,
                seqno,
                boundary_via,
                fir_uir_latitude,
                fir_uir_longitude,
                arc_origin_latitude,
                arc_origin_longitude,
                arc_distance,
                area_code
            FROM tbl_fir_uir
            ORDER BY rowid ASC
        """)
        
        firs = []
        current_id = None
        current_name = ""
        current_indicator = ""
        current_coords = []
        prev_seqno = 99999
        
        def safe_append_fir():
            if current_id is not None and len(current_coords) > 2:
                if current_coords[0] != current_coords[-1]:
                    current_coords.append(current_coords[0])
                
                fixed_coords = self._ensure_ccw(current_coords)
                
                firs.append(AreaFir(
                    identifier=current_id,
                    nome=current_name,
                    indicador=current_indicator,
                    coordenadas=[fixed_coords]
                ))

        for row in cursor.fetchall():
            seqno = row["seqno"]
            area_code = row["area_code"] or ""
            identifier = row["fir_uir_identifier"] or ""
            indicator = row["fir_uir_indicator"] or ""
            f_name = row["fir_uir_name"] or ""
            
            # Use indicator to distinguish FIR from UIR of same identifier
            area_id = f"{area_code}_{identifier}_{indicator}"
            
            if seqno <= prev_seqno or area_id != current_id:
                safe_append_fir()
                current_id = area_id
                
                # Nomenclatura solicitada: FIR BRASILIA SBBS
                # Limpamos possíveis ocorrências de "FIR" ou "UIR" que já vêm no banco
                clean_name = f_name.upper().replace(" FIR", "").replace("FIR ", "").replace(" UIR", "").replace("UIR ", "").strip()
                if not clean_name:
                    clean_name = identifier
                    
                prefix = "FIR" if indicator == 'F' else "UIR"
                current_name = f"{prefix} {clean_name} {identifier}"
                current_indicator = indicator
                current_coords = []
                
            prev_seqno = seqno
            
            b_via = row["boundary_via"]
            lat = row["fir_uir_latitude"]
            lon = row["fir_uir_longitude"]
            arc_lat = row["arc_origin_latitude"]
            arc_lon = row["arc_origin_longitude"]
            arc_dist = row["arc_distance"]
            
            if b_via in ('C', 'CE') and arc_lat is not None and arc_lon is not None and arc_dist is not None:
                circle_coords = self._gerar_circulo(arc_lat, arc_lon, arc_dist)
                current_coords.extend(circle_coords)
            elif lat is not None and lon is not None:
                current_coords.append([lon, lat])
                
        safe_append_fir()
            
        return firs