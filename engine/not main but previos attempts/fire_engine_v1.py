import requests
import geopandas as gpd
from shapely.geometry import Point, shape
from google import genai
import time

# 1. SETUP GEMINI AI
# Paste your Google AI Studio API key here
client = genai.Client(api_key="AQ.Ab8RN6LPoZAmZkMR0-laBAzjgDLeLRxQYnVhYTQh7oliwaykzg")

# 2. THE ALL-INDIA NASA DATASET (Mocking 3 fires across India)
india_fires = [
    {"location": "Visakhapatnam", "lon": 83.275, "lat": 17.685, "temp": 450, "frp": 120.5},
    {"location": "Random Farm in Punjab", "lon": 75.850, "lat": 30.900, "temp": 320, "frp": 15.2},
    {"location": "Mumbai Refinery", "lon": 72.895, "lat": 19.015, "temp": 480, "frp": 185.0}
]


# 3. THE DYNAMIC SPATIAL ENGINE FUNCTION
def check_industrial_fire(fire_data):
    lon, lat = fire_data["lon"], fire_data["lat"]
    print(f"\nScanning Fire at {fire_data['location']} ({lat}, {lon})...")

    # Create a tiny 1km bounding box around the fire
    bbox_offset = 0.01
    bbox = f"{lat - bbox_offset},{lon - bbox_offset},{lat + bbox_offset},{lon + bbox_offset}"

    # Ask OSM if there are ANY industrial zones within this tiny box
    overpass_url = "https://overpass-api.de/api/interpreter"
    overpass_query = f"""
        [out:json];
        way["landuse"="industrial"]({bbox});
        out geom;
        """

    # THE FIX: Add a User-Agent and wrap the query in a dictionary
    headers = {
        'User-Agent': 'NTRO_Fire_Monitor_Hackathon_Test'
    }

    response = requests.post(overpass_url, data={'data': overpass_query}, headers=headers)

    # Adding a safety print to catch future errors before they crash
    if response.status_code != 200:
        print(f"API ERROR: Server returned status {response.status_code}")
        print(response.text)
        return

    osm_data = response.json()

    if len(osm_data['elements']) == 0:
        print("-> Result: Open field or farm. NO INDUSTRIAL THREAT. Skipping AI.")
        return

    print("-> Result: SPATIAL OVERLAP DETECTED! Factory boundary found.")

    # 4. TRIGGER AI PROMPT
    prompt = f"""
    You are an automated industrial safety intelligence system for NTRO. 
    A thermal anomaly has been mathematically confirmed inside an industrial zone in India.

    Data:
    - Region: {fire_data['location']}
    - Temperature: {fire_data['temp']} Kelvin
    - Fire Radiative Power (FRP): {fire_data['frp']} Megawatts

    Generate a 3-bullet-point emergency assessment report. 
    Classify the threat level (Low/Medium/Critical) based on an FRP of > 100 MW being Critical.
    Output strictly as a JSON object with keys: "region", "threat_level", "bullet_points".
    """

    ai_response = client.models.generate_content(
        model='gemini-3.6-flash',
        contents=prompt,
    )

    print("\n--- GEMINI AI THREAT ASSESSMENT ---")
    print(ai_response.text)


# 5. EXECUTE THE LOOP
for fire in india_fires:
    check_industrial_fire(fire)
    time.sleep(2)  # Pauses for 2 seconds to prevent API timeouts