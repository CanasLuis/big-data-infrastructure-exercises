import json
import psycopg2
from collections import Counter
from bdi_api.settings import DBCredentials

db_credentials = DBCredentials()
conn = psycopg2.connect(
    host=db_credentials.host,
    port=db_credentials.port,
    dbname="postgres",  # ← esta es tu base, ya lo vimos
    user=db_credentials.username,
    password=db_credentials.password
)
cursor = conn.cursor()

cursor.execute("""
    SELECT type FROM aircraft_positions
    WHERE type IS NOT NULL AND type != ''
""")

types = [row[0] for row in cursor.fetchall()]
most_common = Counter(types).most_common()  # ← puedes aumentar este número si quieres


fuel_consumption_rates = {
    type_code: {
        "name": type_code,
        "galph": None,         
        "category": "Unknown", 
        "source": "based on aircraft_positions"
    }
    for type_code, _ in most_common
}

# Guardar el JSON en la ruta correcta
output_path = 'bdi_api/s8/aircraft_type_fuel_consumption_rates.json'
with open(output_path, 'w') as f:
    json.dump(fuel_consumption_rates, f, indent=4)

print(f" JSON file created with {len(fuel_consumption_rates)} aircraft types at: {output_path}")

# Cerrar conexión
cursor.close()
conn.close()
