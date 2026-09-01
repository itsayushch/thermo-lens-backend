import numpy as np
import pandas as pd

def apply_layer3_thermodynamic_context(df):
    """
    LAYER 3: THERMODYNAMIC CONTEXT ENGINE
    Separates localized fires from regional summer heatwaves using
    dynamic background deviation and absolute Earth thermodynamic limits.
    """
    if df.empty:
        return df

    # 1. Dynamic Contrast Calculations (Target vs. Background)
    t4_contrast = df['fp_t4'] - df['fp_mean_t4']
    dt_contrast = (df['fp_t4'] - df['fp_t5']) - df['fp_mean_dt']

    # 2. Dynamic Thresholds (Scaling with local geography variance)
    # NASA ATBD formula: Base threshold + (Multiplier * Mean Absolute Deviation)
    dynamic_t4_thresh = np.maximum(4.0, 3.0 * df['fp_mad_t4'])
    dynamic_dt_thresh = np.maximum(2.5, 3.0 * df['fp_mad_dt'])

    # 3. The Core Contextual Test
    # Target must pierce through the local background heat statistically.
    passes_context = (t4_contrast >= dynamic_t4_thresh) & (dt_contrast >= dynamic_dt_thresh)

    # 4. TRAP PREVENTION: Missing Backgrounds
    # If surrounding pixels are clouds/ocean, background is invalid (< 200K).
    # We keep these points so Layer 4 can investigate them. We NEVER delete them here.
    missing_background = df['fp_mean_t4'] < 200.0

    # 5. THE BULLETPROOF PHYSICS OVERRIDE (Replaces the flawed FRP logic)
    # Independent of the background, these conditions prove combustion:
    # A: Target T4 >= 360K (Physically impossible for natural ground heating)
    # B: Target (T4 - T5) >= 15K (Wien's displacement proves an intense sub-pixel heat source)
    absolute_physics_override = (df['fp_t4'] >= 360.0) | ((df['fp_t4'] - df['fp_t5']) >= 15.0)

    # 6. Execution Logic
    is_valid_fire = passes_context | absolute_physics_override | missing_background

    # Drop the weather anomalies (hot sand, warm asphalt, barren rock)
    cleaned_df = df[is_valid_fire].copy().reset_index(drop=True)

    # --- Forensic Audit Logging ---
    weather_noise_dropped = (~is_valid_fire).sum()
    saved_by_override = absolute_physics_override.sum()

    print("=" * 70)
    print("🛰️ LAYER 3 AUDIT: THERMODYNAMIC CONTEXT ENGINE")
    print("=" * 70)
    print(f"• Regional Heat/Warm Terrain Dropped : {weather_noise_dropped}")
    print(f"• True Fires Passed via Context      : {passes_context.sum()}")
    print(f"• Extreme Fires Saved via Physics    : {saved_by_override}")
    print(f"✅ Clean Hotspots Passed to L4       : {len(cleaned_df)}")
    print("=" * 70)

    return cleaned_df