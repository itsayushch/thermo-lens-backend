import geopandas as gpd
import pandas as pd


def get_live_fires():
    print("1. Loading and standardizing NASA fire feeds...")

    # Notice we added 'data/' because this script runs from the project root!
    files = {
        'MODIS': 'data/MODIS_C6_1_South_Asia_24h.csv',
        'VIIRS_SUOMI': 'data/SUOMI_VIIRS_C2_South_Asia_24h.csv',
        'VIIRS_NOAA20': 'data/J1_VIIRS_C2_South_Asia_24h.csv',
        'VIIRS_NOAA21': 'data/J2_VIIRS_C2_South_Asia_24h.csv'
    }

    cols_to_keep = ['latitude', 'longitude', 'acq_date', 'acq_time', 'satellite', 'confidence', 'frp', 'daynight']
    all_dfs = []

    for name, filepath in files.items():
        try:
            df = pd.read_csv(filepath)[cols_to_keep]

            # Normalize Confidence
            if name != 'MODIS':
                conf_mapping = {'low': 25, 'nominal': 70, 'high': 95}
                df['confidence'] = df['confidence'].map(conf_mapping)
            else:
                df['confidence'] = pd.to_numeric(df['confidence'])

            all_dfs.append(df)
        except Exception as e:
            print(f"  [!] Could not load {filepath}: {e}")

    master_df = pd.concat(all_dfs, ignore_index=True)

    # Calculate Threat Score
    master_df['threat_score'] = master_df['frp'] * (master_df['confidence'] / 100.0)

    # Convert to Spatial Points
    fires_gdf = gpd.GeoDataFrame(
        master_df,
        geometry=gpd.points_from_xy(master_df.longitude, master_df.latitude),
        crs="EPSG:4326"
    )
    return fires_gdf


def run_god_eye():
    # Load Fires
    fires_gdf = get_live_fires()
    print(f"   -> Loaded {len(fires_gdf)} active fires across South Asia.")

    # Load Map
    print("\n2. Loading Map Data...")
    map_gdf = gpd.read_file("export.geojson")
    print(f"   -> Loaded local zones (Residential, Farmland, Industrial, etc.)")

    # STEP 3: THE SPATIAL JOIN (The God Eye)
    print("\n3. EXECUTING GOD EYE SPATIAL JOIN...")

    # This single line of math filters out all 1,600+ fires EXCEPT the ones inside your map!
    active_threats = gpd.sjoin(fires_gdf, map_gdf, how="inner", predicate="intersects")

    if len(active_threats) == 0:
        print("\n✅ ALL CLEAR: No active fires detected inside your map boundaries at this time.")
    else:
        print(f"\n⚠️ CRITICAL ALERT: {len(active_threats)} FIRE(S) DETECTED INSIDE MONITORED ZONES!")

        # Display the crucial info for each detected threat
        for index, threat in active_threats.iterrows():
            zone_type = threat.get('landuse', 'Unknown Zone')
            zone_name = threat.get('name', 'Unnamed Location')
            score = round(threat['threat_score'], 1)

            print(f"   🔥 THREAT IDENTIFIED:")
            print(f"      - Location: {zone_name} ({zone_type})")
            print(f"      - Threat Score: {score} (Raw FRP: {threat['frp']})")
            print(f"      - Satellite Time: {threat['acq_date']} {threat['acq_time']} UTC")
            print(f"      - Coordinates: {threat['latitude']}, {threat['longitude']}\n")


if __name__ == "__main__":
    run_god_eye()