import pandas as pd
import geopandas as gpd


def load_and_standardize_nasa_data():
    print("Loading and unifying NASA satellite feeds...")

    files = {
        'MODIS': 'MODIS_C6_1_South_Asia_24h.csv',
        'VIIRS_SUOMI': 'SUOMI_VIIRS_C2_South_Asia_24h.csv',
        'VIIRS_NOAA20': 'J1_VIIRS_C2_South_Asia_24h.csv',
        'VIIRS_NOAA21': 'J2_VIIRS_C2_South_Asia_24h.csv'
    }

    # Columns we actually care about
    cols_to_keep = ['latitude', 'longitude', 'acq_date', 'acq_time', 'satellite', 'confidence', 'frp', 'daynight']

    all_dfs = []

    for name, filepath in files.items():
        try:
            df = pd.read_csv(filepath)
            df = df[cols_to_keep].copy()  # Filter down to essentials

            # 1. Normalize Confidence to 0-100 scale
            if name != 'MODIS':
                # Map VIIRS text to numeric percentages
                conf_mapping = {'low': 25, 'nominal': 70, 'high': 95}
                df['confidence'] = df['confidence'].map(conf_mapping)
            else:
                # MODIS is already numeric, just ensure it's an integer
                df['confidence'] = pd.to_numeric(df['confidence'])

            all_dfs.append(df)
            print(f"[{name}] Successfully loaded {len(df)} fire points.")
        except Exception as e:
            print(f"Error loading {name}: {e}")

    # Combine all satellites into one master dataset
    master_df = pd.concat(all_dfs, ignore_index=True)

    # 2. Time-Syncing: Convert date and time into a single powerful Datetime object
    # NASA 'acq_time' is an integer like 1430 (2:30 PM), we pad it to be '1430' string
    master_df['acq_time_str'] = master_df['acq_time'].astype(str).str.zfill(4)
    master_df['datetime_utc'] = pd.to_datetime(
        master_df['acq_date'] + ' ' + master_df['acq_time_str'],
        format='%Y-%m-%d %H%M'
    )

    # 3. The Custom Threat Score
    master_df['threat_score'] = master_df['frp'] * (master_df['confidence'] / 100.0)

    # 4. Clean up columns and convert to Spatial format (GeoDataFrame)
    final_cols = ['latitude', 'longitude', 'datetime_utc', 'satellite', 'confidence', 'frp', 'threat_score', 'daynight']
    master_df = master_df[final_cols]

    # Turn latitude/longitude into a GeoPandas Geometry Point (needed for the spatial join!)
    gdf_fires = gpd.GeoDataFrame(
        master_df,
        geometry=gpd.points_from_xy(master_df.longitude, master_df.latitude),
        crs="EPSG:4326"  # Standard GPS coordinate system
    )

    return gdf_fires


# --- RUN IT ---
if __name__ == "__main__":
    fires_gdf = load_and_standardize_nasa_data()
    print("\n--- MASTER FIRE FEED READY ---")
    print(f"Total Unique Fire Detections: {len(fires_gdf)}")
    print(fires_gdf.head())
    print("Missing coordinates:", fires_gdf[['latitude', 'longitude']].isna().sum().to_dict())