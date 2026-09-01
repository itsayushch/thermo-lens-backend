import pandas as pd
import numpy as np


def calculate_thermal_contrast():
    print("1. Loading files from data/ folder...")

    modis_path = 'data/MODIS_C6_1_South_Asia_24h.csv'
    viirs_paths = [
        'data/SUOMI_VIIRS_C2_South_Asia_24h.csv',
        'data/J1_VIIRS_C2_South_Asia_24h.csv',
        'data/J2_VIIRS_C2_South_Asia_24h.csv'
    ]

    # --- 1. HANDLE MODIS ---
    try:
        df_modis = pd.read_csv(modis_path)
        # Delta T = Fire Core (brightness) - Background (bright_t31)
        df_modis['delta_T'] = df_modis['brightness'] - df_modis['bright_t31']
        df_modis = df_modis[['latitude', 'longitude', 'satellite', 'frp', 'delta_T']]
        print(f" -> Processed {len(df_modis)} MODIS records.")
    except Exception as e:
        print(f" [!] Error loading MODIS: {e}")
        df_modis = pd.DataFrame()

    # --- 2. HANDLE VIIRS ---
    viirs_dfs = []
    for path in viirs_paths:
        try:
            df_v = pd.read_csv(path)
            # Delta T = Fire Core (bright_ti4) - Background (bright_ti5)
            df_v['delta_T'] = df_v['bright_ti4'] - df_v['bright_ti5']
            df_v = df_v[['latitude', 'longitude', 'satellite', 'frp', 'delta_T']]
            viirs_dfs.append(df_v)
        except Exception as e:
            print(f" [!] Error loading VIIRS {path}: {e}")

    if viirs_dfs:
        df_viirs = pd.concat(viirs_dfs, ignore_index=True)
        print(f" -> Processed {len(df_viirs)} VIIRS records.")
    else:
        df_viirs = pd.DataFrame()

    # --- 3. MERGE AND CALCULATE Z-SCORE ---
    print("\n2. Merging datasets and calculating Z-Scores...")
    master_df = pd.concat([df_modis, df_viirs], ignore_index=True)

    # Calculate Statistical Mean and Standard Deviation of Delta T
    mean_dt = master_df['delta_T'].mean()
    std_dt = master_df['delta_T'].std()

    # Z-Score Formula: z = (Value - Mean) / Standard Deviation
    master_df['z_score'] = (master_df['delta_T'] - mean_dt) / std_dt

    print(f" -> System Mean Delta T: {mean_dt:.2f} Kelvin")
    print(f" -> System Std Dev: {std_dt:.2f} Kelvin")

    return master_df


if __name__ == "__main__":
    df = calculate_thermal_contrast()
    print("\n--- STEP 1 OUTPUT (First 5 Rows) ---")
    print(df.head())