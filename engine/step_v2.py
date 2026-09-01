import pandas as pd
import numpy as np
import math
import requests
import time
from datetime import datetime, timedelta
import geopandas as gpd
from shapely.geometry import Point
from google import genai


# ==========================================
# MATHEMATICAL UTILITIES & SANITY GATES
# ==========================================
def normal_cdf(z_series):
    erf_vec = np.vectorize(math.erf)
    return 0.5 * (1.0 + erf_vec(z_series / np.sqrt(2.0))) * 100.0


def enforce_sanity_bounds(df):
    if df.empty:
        return df
    df = df.dropna(subset=['latitude', 'longitude', 'frp', 'delta_T'])
    df['round_lat'] = df['latitude'].round(3)
    df['round_lon'] = df['longitude'].round(3)
    df = df.drop_duplicates(subset=['round_lat', 'round_lon'])
    df = df.drop(columns=['round_lat', 'round_lon'])
    df = df[(df['frp'] > 0) & (df['delta_T'] > 0)]
    df.loc[df['frp'] > 10000, 'frp'] = 10000
    return df


# ==========================================
# LAYER 1: STATISTICAL BASELINE ENGINE
# ==========================================
def build_hierarchical_confidence():
    print("\n--- LAYER 1: STATISTICAL BASELINE ---")
    modis_path = 'data/MODIS_C6_1_South_Asia_24h.csv'
    viirs_paths = [
        'data/SUOMI_VIIRS_C2_South_Asia_24h.csv',
        'data/J1_VIIRS_C2_South_Asia_24h.csv',
        'data/J2_VIIRS_C2_South_Asia_24h.csv'
    ]

    try:
        df_modis = pd.read_csv(modis_path)
        df_modis['delta_T'] = df_modis['brightness'] - df_modis['bright_t31']
        df_modis = df_modis[['latitude', 'longitude', 'acq_date', 'acq_time', 'satellite', 'frp', 'delta_T']]
    except:
        df_modis = pd.DataFrame()

    viirs_dfs = []
    for path in viirs_paths:
        try:
            df_v = pd.read_csv(path)
            df_v['delta_T'] = df_v['bright_ti4'] - df_v['bright_ti5']
            df_v = df_v[['latitude', 'longitude', 'acq_date', 'acq_time', 'satellite', 'frp', 'delta_T']]
            viirs_dfs.append(df_v)
        except:
            pass

    # FIXED: Properly handle concatenating all valid DataFrames
    all_frames = [df_modis] + viirs_dfs
    valid_frames = [f for f in all_frames if not f.empty]

    if not valid_frames:
        print(" [!] No telemetry data loaded.")
        return pd.DataFrame()

    master_df = pd.concat(valid_frames, ignore_index=True)
    master_df = enforce_sanity_bounds(master_df)

    global_median = master_df['delta_T'].median()
    global_mad = (master_df['delta_T'] - global_median).abs().median()
    if global_mad == 0:
        global_mad = 1.0

    master_df['grid_lat'] = (master_df['latitude'] * 2).round() / 2
    master_df['grid_lon'] = (master_df['longitude'] * 2).round() / 2

    def calculate_local_robust_z(group):
        if len(group) < 3:
            loc_med, loc_mad = global_median, global_mad
        else:
            loc_med = group['delta_T'].median()
            loc_mad = (group['delta_T'] - loc_med).abs().median()
            if loc_mad == 0:
                loc_mad = global_mad
        return (0.6745 * (group['delta_T'] - loc_med)) / loc_mad

    master_df['robust_z'] = master_df.groupby(['grid_lat', 'grid_lon'], group_keys=False).apply(
        calculate_local_robust_z)
    master_df['dynamic_confidence'] = normal_cdf(master_df['robust_z']).round(1)

    return master_df


# ==========================================
# LAYER 2: SPATIAL & SOLAR GLINT MASK (UPGRADED)
# ==========================================
def apply_infrastructure_mask(df, gpkg_path='/content/drive/MyDrive/india_features.gpkg'):
    print("\n--- LAYER 2: SPATIAL & SOLAR GLINT MASK ---")
    if df.empty:
        return df

    # Prepare geometry
    geometry = [Point(xy) for xy in zip(df.longitude, df.latitude)]
    geo_df = gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:4326")

    processed_chunks = []

    # Process by regional grid to save RAM and minimize GPKG disk reads
    for (glat, glon), group in geo_df.groupby(['grid_lat', 'grid_lon']):
        buffer = 0.05
        minx, maxx = group.longitude.min() - buffer, group.longitude.max() + buffer
        miny, maxy = group.latitude.min() - buffer, group.latitude.max() + buffer

        try:
            # Query ONLY the polygons inside this specific regional box
            local_map = gpd.read_file(gpkg_path, layer='india_polygons', bbox=(minx, miny, maxx, maxy))

            if not local_map.empty:
                if local_map.crs is None:
                    local_map.set_crs(epsg=4326, inplace=True)
                else:
                    local_map = local_map.to_crs(epsg=4326)

                # Spatial join for this chunk
                joined = gpd.sjoin(group, local_map, how="left", predicate="intersects")
                joined['is_infrastructure_flare'] = joined['index_right'].notna()
                joined = joined.drop_duplicates(subset=['latitude', 'longitude'])
            else:
                group['is_infrastructure_flare'] = False
                joined = group
        except Exception as e:
            print(f" [!] Map load error for grid {glat},{glon}: {e}")
            group['is_infrastructure_flare'] = False
            joined = group

        processed_chunks.append(joined)

    final_df = pd.concat(processed_chunks, ignore_index=True)

    # Solar Glint Physics
    utc_hour = (final_df['acq_time'] // 100) + ((final_df['acq_time'] % 100) / 60.0)
    local_solar_time = (utc_hour + (final_df['longitude'] / 15.0)) % 24.0

    is_daytime = (local_solar_time >= 8.0) & (local_solar_time <= 17.0)
    final_df['is_sun_glint'] = final_df['is_infrastructure_flare'] & is_daytime

    mask_flare = (final_df['is_infrastructure_flare'] == True) & (final_df['is_sun_glint'] == False)
    final_df.loc[mask_flare, 'dynamic_confidence'] = 15.0

    mask_glint = final_df['is_sun_glint'] == True
    final_df.loc[mask_glint, 'dynamic_confidence'] = 0.0

    cols_to_keep = ['satellite', 'latitude', 'longitude', 'acq_date', 'acq_time',
                    'frp', 'delta_T', 'dynamic_confidence', 'is_infrastructure_flare', 'is_sun_glint']
    return pd.DataFrame(final_df[[c for c in cols_to_keep if c in final_df.columns]])


# ==========================================
# LAYER 3: ATMOSPHERIC MULTIPLIER (UPGRADED)
# ==========================================
def apply_atmospheric_multiplier(df, limit=3):
    print("\n--- LAYER 3: ATMOSPHERIC MULTIPLIER ---")
    if df.empty:
        return df

    threats = df[df['is_infrastructure_flare'] == False].copy()
    threats = threats.sort_values(by='dynamic_confidence', ascending=False).head(limit)

    cloud_covers, final_scores = [], []
    weather_cache = {}  # Solves the API rate limit bottleneck

    for index, row in threats.iterrows():
        lat, lon = row['latitude'], row['longitude']

        # Round to 1 decimal (~11km) to group nearby fires into the same weather cell
        grid_key = (round(lat, 1), round(lon, 1))

        if grid_key in weather_cache:
            cc = weather_cache[grid_key]
            print(f" [API Cache Hit] Using stored cloud data for grid {grid_key}")
        else:
            time_str = str(int(row['acq_time'])).zfill(4)
            datetime_str = f"{row['acq_date']} {time_str}"
            try:
                dt_obj = datetime.strptime(datetime_str, "%Y-%m-%d %H%M")
                if dt_obj.minute >= 30:
                    dt_obj += timedelta(hours=1)
                api_hour_iso = dt_obj.replace(minute=0, second=0).strftime("%Y-%m-%dT%H:00")
                api_date = dt_obj.strftime("%Y-%m-%d")

                url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&start_date={api_date}&end_date={api_date}&hourly=cloudcover"
                resp = requests.get(url, timeout=5).json()
                cc = resp['hourly']['cloudcover'][resp['hourly']['time'].index(api_hour_iso)]
                weather_cache[grid_key] = cc  # Save to cache
                time.sleep(0.1)  # Be polite to the API
            except:
                cc = 0

        cloud_covers.append(cc)

        # Exponential Beer-Lambert Heuristic
        multiplier = math.exp(1.5 * (cc / 100.0))
        final_scores.append(round(min(row['dynamic_confidence'] * multiplier, 100.0), 1))

    threats['cloud_cover_pct'] = cloud_covers
    threats['final_threat_score'] = final_scores
    return threats

# ==========================================
# LAYER 4: AI DISPATCH GENERATOR
# ==========================================
def generate_dispatch_alerts(threats_df):
    print("\n--- LAYER 4: AI DISPATCH GENERATOR ---")
    if threats_df.empty:
        print(" [!] No active threats found to dispatch.")
        return

    # Replace with your actual Gemini API key
    client = genai.Client(api_key="AQ.Ab8RN6LPoZAmZkMR0-laBAzjgDLeLRxQYnVhYTQh7oliwaykzg")

    for index, row in threats_df.iterrows():
        print(f"\n[Processing Lat: {row['latitude']}, Lon: {row['longitude']}]")

        prompt = f"""
        You are an emergency automated dispatch system. 
        Write a strict, 2-sentence SMS alert for the local fire department using this verified data:

        - Location: {row['latitude']}, {row['longitude']}
        - System Threat Score: {row['final_threat_score']}%
        - Satellite Thermal Spike (Delta T): {row['delta_T']} degrees
        - Current Cloud Cover: {row['cloud_cover_pct']}%

        Do not explain the math. Do not add warnings. Just write the SMS format.dont over or change any thing i already did the maths
        you just need to formate in a way that is readable understable graspable and professorial for judges. remember, just data no fluff because im using you as brain 
        to feed  the backend the data and then to frontend to display on website or portal so be act like that
        """


        try:
            response = client.models.generate_content(
                model='gemini-3.6-flash',
                contents=prompt
            )
            print("🚨 DISPATCH SMS 🚨")
            print(response.text.strip())

        except Exception as e:
            print(f" [!] API Error: {e}")


# ==========================================
# EXECUTION WORKFLOW
# ==========================================
if __name__ == "__main__":
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)

    # Execute Pipeline
    df_layer1 = build_hierarchical_confidence()

    # PYCHARM FIX: Use the local file path where you saved the GPKG
    df_layer2 = apply_infrastructure_mask(df_layer1, 'india_features.gpkg')

    df_layer3 = apply_atmospheric_multiplier(df_layer2, limit=3)

    # Final Translation
    generate_dispatch_alerts(df_layer3)