import pandas as pd
import numpy as np
import math


def normal_cdf(z_series):
    erf_vec = np.vectorize(math.erf)
    return 0.5 * (1.0 + erf_vec(z_series / np.sqrt(2.0))) * 100.0


def enforce_sanity_bounds(df):
    print(" -> Running Production Sanity Checks...")
    initial_len = len(df)

    # 1. Drop Phantom Nulls (Rows missing critical math values)
    df = df.dropna(subset=['latitude', 'longitude', 'frp', 'delta_T'])

    # 2. Deduplicate (Same location within the same timeframe)
    # Rounding coordinates slightly to catch slight satellite alignment differences
    df['round_lat'] = df['latitude'].round(3)
    df['round_lon'] = df['longitude'].round(3)
    df = df.drop_duplicates(subset=['round_lat', 'round_lon'])
    df = df.drop(columns=['round_lat', 'round_lon'])

    # 3. Physics Gates (Must be hotter than background, FRP > 0)
    df = df[(df['frp'] > 0) & (df['delta_T'] > 0)]

    # 4. Cap Apocalyptic Outliers (Preventing Black Swan math skew)
    df.loc[df['frp'] > 10000, 'frp'] = 10000

    dropped = initial_len - len(df)
    print(f" -> Sanitization complete. Dropped {dropped} corrupted/duplicate rows.")
    return df


def build_hierarchical_confidence():
    print("1. Ingesting NASA Telemetry & Preserving Coordinates...")

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

    df_viirs = pd.concat(viirs_dfs, ignore_index=True) if viirs_dfs else pd.DataFrame()
    master_df = pd.concat([df_modis, df_viirs], ignore_index=True)

    # --- APPLY SANITY GATE ---
    master_df = enforce_sanity_bounds(master_df)

    global_median = master_df['delta_T'].median()
    global_mad = (master_df['delta_T'] - global_median).abs().median()
    if global_mad == 0:
        global_mad = 1.0

    print("2. Partitioning into 0.5° Spatial Grid Bins for Local Baselines...")
    master_df['grid_lat'] = (master_df['latitude'] * 2).round() / 2
    master_df['grid_lon'] = (master_df['longitude'] * 2).round() / 2

    def calculate_local_robust_z(group):
        if len(group) < 3:
            loc_med = global_median
            loc_mad = global_mad
        else:
            loc_med = group['delta_T'].median()
            loc_mad = (group['delta_T'] - loc_med).abs().median()
            if loc_mad == 0:
                loc_mad = global_mad

        return (0.6745 * (group['delta_T'] - loc_med)) / loc_mad

    master_df['robust_z'] = master_df.groupby(['grid_lat', 'grid_lon'], group_keys=False).apply(
        calculate_local_robust_z)

    print("3. Converting Local Z-Scores to Percentile Probabilities...")
    master_df['dynamic_confidence'] = normal_cdf(master_df['robust_z'])

    master_df['dynamic_confidence'] = master_df['dynamic_confidence'].round(1)
    master_df['robust_z'] = master_df['robust_z'].round(2)
    master_df['delta_T'] = master_df['delta_T'].round(2)

    return master_df


if __name__ == "__main__":
    df = build_hierarchical_confidence()
    print("\n--- SAMPLE OUTPUT (Sanitized & Evaluated) ---")
    print(df[['satellite', 'latitude', 'longitude', 'delta_T', 'robust_z', 'dynamic_confidence', 'frp']].head(6))