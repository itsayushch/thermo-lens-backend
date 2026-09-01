import os
import netCDF4 as nc
import numpy as np
import pandas as pd

def apply_layer4_qa_and_obscuration(df, file_path):
    """
    LAYER 4: ATMOSPHERIC OPTICS & QUALITY ASSURANCE (CRASH-PROOFED)
    Decodes the 32-bit QA bitmask using NumPy arrays to prevent type errors.
    """
    if df.empty:
        return df

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"L2 NetCDF file missing for Layer 4: {file_path}")

    # 1. Open the 2D NASA Physics Matrices
    ds = nc.Dataset(file_path, 'r')
    qa_2d_array = ds.variables['algorithm QA'][:]
    fire_mask_2d = ds.variables['fire mask'][:]
    ds.close()

    # 2. Extract X/Y Array Coordinates for our detected fires
    lines = df['fp_line'].astype(int).values
    samples = df['fp_sample'].astype(int).values

    # 3. Vectorized Indexing: Extract raw values from matrices
    qa_raw = qa_2d_array[lines, samples]
    mask_raw = fire_mask_2d[lines, samples]

    # 🚨 THE ROOT CAUSE FIX: NASA NetCDF arrays often contain masked values or NaNs.
    # When assigned to a Pandas column, Pandas silently converts the whole column to float64.
    # Bitwise shift (>>) on a float Series throws a TypeError instantly.
    # Converting them explicitly to clean NumPy int64 arrays completely eliminates this.
    qa_ints = np.nan_to_num(qa_raw, nan=0).astype(np.int64)
    mask_ints = np.nan_to_num(mask_raw, nan=0).astype(np.int64)

    df['qa_32bit'] = qa_ints
    df['fire_mask_code'] = mask_ints

    # 4. RIGOROUS BITWISE DECODING USING NUMPY ARRAYS
    # Operating directly on NumPy int64 arrays guarantees a 100% crash-proof bit shift.
    df['nasa_glint_flag'] = (qa_ints >> 2) & 1
    df['is_cloud_attenuated'] = (qa_ints >> 22) & 1

    # 5. Safety Filter: Drop anything NASA flagged as 'Not Fire' in the final mask
    is_valid_mask = df['fire_mask_code'] >= 7

    cleaned_df = df[is_valid_mask].copy().reset_index(drop=True)

    print("=" * 70)
    print("🛰️ LAYER 4 AUDIT: ATMOSPHERIC QA & MASKING")
    print("=" * 70)
    print(f"• Cloud-Attenuated Fires Tagged for AI : {cleaned_df['is_cloud_attenuated'].sum()}")
    print(f"• NASA Final Mask Rejections Dropped   : {(~is_valid_mask).sum()}")
    print(f"✅ ULTIMATE CLEAN PIPELINE OUTPUT      : {len(cleaned_df)}")
    print("=" * 70)

    return cleaned_df.drop(columns=['qa_32bit', 'fire_mask_code'])

# =====================================================================
# THE "INVISIBLE FIRE" LOOKUP FUNCTION (To use during daily live runs)
# =====================================================================
def check_missing_factory(file_path, factory_line, factory_sample):
    """
    If a known factory is NOT in today's fire list, run this function
    to mathematically prove if it shut down or is just covered by clouds.
    """
    ds = nc.Dataset(file_path, 'r')
    fire_mask_2d = ds.variables['fire mask'][:]
    ds.close()

    status_code = fire_mask_2d[factory_line, factory_sample]

    if status_code == 4:
        return "OBSCURED_BY_CLOUD (Do not train ML today)"
    elif status_code == 5:
        return "CLEAR_LAND_SHUTDOWN (Train ML with 0 MW)"
    else:
        return "UNKNOWN_STATUS"