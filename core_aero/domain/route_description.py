import sqlite3
import re
from typing import List, Dict, Optional

class RouteService:
    def __init__(self, db_path: str):
        self.db_path = db_path

    @staticmethod
    def clean_wp_name(wp: str) -> str:
        return wp.split('/')[0].strip()

    @staticmethod
    def get_level_from_wp(wp: str, current_level: int) -> int:
        match = re.search(r'F(\d+)', wp)
        if match:
            return int(match.group(1))
        return current_level

    def get_waypoint_coords(self, wp_name: str) -> Optional[tuple[float, float]]:
        wp_clean = self.clean_wp_name(wp_name)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 1. Check enroute waypoints
        cursor.execute(
            'SELECT waypoint_latitude, waypoint_longitude FROM tbl_enroute_waypoints WHERE waypoint_identifier = ?',
            (wp_clean,)
        )
        row = cursor.fetchone()
        if row:
            conn.close()
            return row[0], row[1]

        # 2. Check terminal waypoints
        cursor.execute(
            'SELECT waypoint_latitude, waypoint_longitude FROM tbl_terminal_waypoints WHERE waypoint_identifier = ?',
            (wp_clean,)
        )
        row = cursor.fetchone()
        if row:
            conn.close()
            return row[0], row[1]
            
        # 3. Check airports
        cursor.execute(
            'SELECT airport_ref_latitude, airport_ref_longitude FROM tbl_airports WHERE airport_identifier = ?',
            (wp_clean,)
        )
        row = cursor.fetchone()
        if row:
            conn.close()
            return row[0], row[1]

        # 4. Check VORs/NDBs
        cursor.execute(
            'SELECT vor_latitude, vor_longitude FROM tbl_vhfnavaids WHERE vor_identifier = ?',
            (wp_clean,)
        )
        row = cursor.fetchone()
        if row:
            conn.close()
            return row[0], row[1]

        conn.close()
        return None

    def get_magnetic_variation(self, lat: float, lon: float) -> float:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT magnetic_variation FROM tbl_vhfnavaids
            ORDER BY ((vor_latitude - ?) * (vor_latitude - ?)) + ((vor_longitude - ?) * (vor_longitude - ?))
            LIMIT 1
        ''', (lat, lat, lon, lon))
        row = cursor.fetchone()
        conn.close()
        if row and row[0] is not None:
            return row[0]
        return -22.0

    def get_route_waypoints(self, start_waypoint: str, airway: str, end_waypoint: str) -> List[dict]:
        start_wp_clean = self.clean_wp_name(start_waypoint)
        end_wp_clean = self.clean_wp_name(end_waypoint)

        if airway.upper() == 'DCT':
            start_coords = self.get_waypoint_coords(start_wp_clean)
            end_coords = self.get_waypoint_coords(end_wp_clean)
            
            mag_course = None
            if start_coords and end_coords:
                import math
                lat1, lon1 = start_coords
                lat2, lon2 = end_coords
                
                r_lat1, r_lon1 = math.radians(lat1), math.radians(lon1)
                r_lat2, r_lon2 = math.radians(lat2), math.radians(lon2)
                
                d_lon = r_lon2 - r_lon1
                x = math.sin(d_lon) * math.cos(r_lat2)
                y = math.cos(r_lat1) * math.sin(r_lat2) - (math.sin(r_lat1) * math.cos(r_lat2) * math.cos(d_lon))
                
                true_bearing = math.degrees(math.atan2(x, y))
                true_course = (true_bearing + 360) % 360
                
                mag_var = self.get_magnetic_variation(lat1, lon1)
                mag_course = round((true_course - mag_var) % 360, 2)

            return [
                {'id': start_wp_clean, 'course': None, 'min': None, 'is_reverse': False, 'restriction': None, 'cruise_table': None},
                {'id': end_wp_clean, 'course': mag_course, 'min': None, 'is_reverse': False, 'restriction': None, 'cruise_table': None}
            ]

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
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
            conn.close()
            raise ValueError(f"Fixo {start_wp_clean if not start_row else end_wp_clean} nao encontrado na {airway}.")

        start_seq, end_seq = start_row[0], end_row[0]
        is_reverse = start_seq > end_seq

        query = f'''
            SELECT waypoint_identifier, minimum_altitude1, maximum_altitude, inbound_course, direction_restriction, crusing_table_identifier
            FROM tbl_enroute_airways
            WHERE route_identifier = ? AND seqno BETWEEN ? AND ?
            ORDER BY seqno {'DESC' if is_reverse else 'ASC'}
        '''
        cursor.execute(query, (airway, min(start_seq, end_seq), max(start_seq, end_seq)))
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                'id': r[0],
                'min': r[1],
                'max': r[2],
                'course': r[3],
                'restriction': r[4],
                'cruise_table': r[5],
                'is_reverse': is_reverse
            } for r in rows
        ]

    def is_course_odd(self, cruise_table_id: Optional[str], course: float) -> bool:
        if not cruise_table_id:
            return 0 <= course < 180

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT course_from, course_to, cruise_level_from2
            FROM tbl_cruising_tables
            WHERE cruise_table_identifier = ?
        ''', (cruise_table_id,))
        rows = cursor.fetchall()
        conn.close()

        matching_row = None
        for row in rows:
            c_from, c_to = row[0], row[1]
            if c_from <= c_to:
                if c_from <= course <= c_to:
                    matching_row = row
                    break
            else:
                if course >= c_from or course <= c_to:
                    matching_row = row
                    break

        if not matching_row or matching_row[2] is None:
            return 0 <= course < 180

        lvl_from2 = matching_row[2]
        fl = lvl_from2 // 100
        return (fl // 10) % 2 != 0

    def process_and_validate_route(self, route_string: str, initial_level: int) -> List[dict]:
        parts = route_string.strip().split()
        full_route_data = []
        current_level = initial_level

        level_map = {}
        for p in parts:
            clean = self.clean_wp_name(p)
            if 'F' in p:
                level_map[clean] = self.get_level_from_wp(p, current_level)

        for i in range(0, len(parts) - 2, 2):
            start_wp_raw, airway, end_wp_raw = parts[i], parts[i+1], parts[i+2]
            segment_waypoints = self.get_route_waypoints(start_wp_raw, airway, end_wp_raw)

            for wp in segment_waypoints:
                if wp['id'] in level_map:
                    current_level = level_map[wp['id']]
                wp['active_level'] = current_level
                wp['airway_ref'] = airway
                if not full_route_data or full_route_data[-1]['id'] != wp['id']:
                    full_route_data.append(wp)
                else:
                    # Preserva os dados do waypoint para a nova aerovia (como o course e restriction)
                    full_route_data[-1]['_next_wp_data'] = wp

        segments = []
        for i in range(len(full_route_data) - 1):
            wp_raw = full_route_data[i]
            nxt = full_route_data[i+1]
            
            # Se for um waypoint de junção, os dados de início do novo segmento estão no _next_wp_data
            wp = wp_raw.get('_next_wp_data', wp_raw)
            
            lvl = wp['active_level']

            # Check Direction Restriction
            restr = wp.get('restriction')
            has_valid_restriction = False
            if restr and restr.strip():
                is_rev = nxt.get('is_reverse')
                if (is_rev and restr.upper() == 'F') or (not is_rev and restr.upper() == 'B'):
                    direction_name = 'Forward-only (F)' if restr.upper() == 'F' else 'Backward-only (B)'
                    raise ValueError(f"Erro em {wp['id']}: Sentido Proibido na {wp['airway_ref']}. Aerovia {direction_name}.")
                else:
                    has_valid_restriction = True

            # Minimum Altitude check
            if wp.get('min') and lvl < (wp['min'] / 100):
                raise ValueError(f"Erro em {wp['id']}: Nivel F{lvl} abaixo do minimo F{int(wp['min']/100)} na {wp['airway_ref']}.")

            # Semicircular Rule
            actual_course = nxt.get('course')
            if not has_valid_restriction:
                course = nxt.get('course')
                if course is not None:
                    actual_course = course
                    if nxt.get('is_reverse'):
                        ref_course = wp.get('course')
                        if ref_course is None:
                            ref_course = course
                        if ref_course is not None:
                            actual_course = (ref_course + 180) % 360
                    
                    is_odd = (lvl // 10) % 2 != 0
                    required_odd = self.is_course_odd(nxt.get('cruise_table'), actual_course)
                    
                    if required_odd and not is_odd:
                        raise ValueError(f"Erro em {wp['id']}: Rumo {int(actual_course)}° exige nível ÍMPAR (Tentado F{lvl}).")
                    elif not required_odd and is_odd:
                        raise ValueError(f"Erro em {wp['id']}: Rumo {int(actual_course)}° exige nível PAR (Tentado F{lvl}).")

            segments.append({
                "from_waypoint": wp['id'],
                "to_waypoint": nxt['id'],
                "airway": nxt.get('airway_ref'),
                "course": round(actual_course, 2) if actual_course is not None else None,
                "active_level": lvl,
                "min_altitude": wp.get('min'),
                "max_altitude": wp.get('max')
            })

        return segments