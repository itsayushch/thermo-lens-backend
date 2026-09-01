import numpy as np
import pandas as pd

def apply_layer2_sunglint_filter(df):
    """
    LAYER 2: SPECULAR REFLECTION & SUN GLINT
    Mathematically isolates solar reflection off water and metal surfaces,
    while utilizing spatial contrast to prevent the deletion of real fires.
    """
    if df.empty:
        return df

    # 1. Convert all orbital angles from degrees to radians
    sol_zen_rad  = np.radians(df['fp_sol_zen'])
    sol_az_rad   = np.radians(df['fp_sol_az'])
    view_zen_rad = np.radians(df['fp_view_zen'])
    view_az_rad  = np.radians(df['fp_view_az'])

    # 2. Compute Exact Specular Glint Angle (theta_g) using Spherical Cosine Law
    cos_glint = (np.cos(view_zen_rad) * np.cos(sol_zen_rad)) - \
                (np.sin(view_zen_rad) * np.sin(sol_zen_rad) * np.cos(view_az_rad - sol_az_rad))

    # Clip limits to prevent NumPy arccos floating point NaN errors
    cos_glint = np.clip(cos_glint, -1.0, 1.0)
    df['glint_angle'] = np.degrees(np.arccos(cos_glint))

    # 3. Define the Glint Danger Zones (Only applies during daytime)
    # Water: Wider scattering angle (10 degrees) due to wave action
    is_water_glint = (df['fp_day'] == 1) & (df['glint_angle'] <= 10.0) & (df['fp_adj_water'] > 0)

    # Land: Ultra-tight angle (2.0 degrees) because metal/glass act as perfect flat mirrors
    is_land_glint = (df['fp_day'] == 1) & (df['glint_angle'] <= 2.0) & (df['fp_adj_water'] == 0)

    # 4. THE BULLETPROOF SPATIAL SAFETY OVERRIDE
    # A fire in a glint zone is ONLY saved if it proves it is an isolated thermal point source:
    # Condition A: It generates an overwhelming radiative power (> 20 MW)
    # Condition B: It stands out sharply (> 15K) against the already-reflecting background
    safety_override = (df['fp_power'] >= 20.0) | ((df['fp_t4'] - df['fp_mean_t4']) >= 15.0)

    # 5. Execution: Flag for deletion ONLY if it is glint AND fails the safety check
    is_false_alarm = (is_water_glint | is_land_glint) & (~safety_override)

    # Optional: Tag borderline reflections so the downstream AI knows it's a noisy environment
    df['is_glint_risk'] = (df['fp_day'] == 1) & (df['glint_angle'] <= 15.0)

    # 6. Apply filter and reset index
    cleaned_df = df[~is_false_alarm].copy().reset_index(drop=True)

    # --- Audit Logging ---
    water_dropped = (is_water_glint & ~safety_override).sum()
    land_dropped  = (is_land_glint & ~safety_override).sum()
    saved_fires   = ((is_water_glint | is_land_glint) & safety_override).sum()

    print("=" * 70)
    print("🛰️ LAYER 2 AUDIT: SUN GLINT & SPECULAR REFLECTION")
    print("=" * 70)
    print(f"• Coastal/Pond Glints Eliminated : {water_dropped}")
    print(f"• Metal Roof Glints Eliminated   : {land_dropped}")
    print(f"• Real Fires Saved by Override   : {saved_fires}")
    print(f"✅ Clean Hotspots Passed to L3   : {len(cleaned_df)}")
    print("=" * 70)

    return cleaned_df