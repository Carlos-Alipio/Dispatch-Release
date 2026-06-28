import sqlite3
from core_aero.domain.matematica import calcular_rumo_magnetico, calcular_distancia_e_rumo

conn = sqlite3.connect("core_aero/data/airac/airac_atual.s3db")
conn.row_factory = sqlite3.Row

def get_coords(wp):
    row = conn.execute("SELECT airport_ref_latitude as lat, airport_ref_longitude as lon FROM tbl_airports WHERE airport_identifier = ?", (wp,)).fetchone()
    if row: return row['lat'], row['lon']
    row = conn.execute("SELECT waypoint_latitude as lat, waypoint_longitude as lon FROM tbl_enroute_waypoints WHERE waypoint_identifier = ?", (wp,)).fetchone()
    if row: return row['lat'], row['lon']
    return None, None

def get_mag(lat, lon):
    row = conn.execute("SELECT magnetic_variation FROM tbl_vhfnavaids ORDER BY ((vor_latitude - ?) * (vor_latitude - ?)) + ((vor_longitude - ?) * (vor_longitude - ?)) LIMIT 1", (lat, lat, lon, lon)).fetchone()
    return row['magnetic_variation'] if row else -22.0

lat1, lon1 = get_coords("SBBE")
lat2, lon2 = get_coords("ANGIM")
mag = get_mag(lat1, lon1)
print(f"SBBE: {lat1}, {lon1}")
print(f"ANGIM: {lat2}, {lon2}")
print(f"Mag Var: {mag}")
print(f"Rumo Verdadeiro: {calcular_distancia_e_rumo(lat1, lon1, lat2, lon2)['rumo_verdadeiro_graus']}")
print(f"Rumo Mag: {calcular_rumo_magnetico(lat1, lon1, lat2, lon2, mag)}")
