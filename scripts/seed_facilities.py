import os
import sys
import pandas as pd
from pathlib import Path
from sqlalchemy import text

# Add root to python path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from db.session import SessionLocal

PARQUET_PATH = Path("data/factory_roster_2yr.parquet")

def seed_database():
    if not PARQUET_PATH.exists():
        print(f"Error: Could not find {PARQUET_PATH}")
        return

    print(f"Loading parquet file {PARQUET_PATH} into Pandas...")
    df = pd.read_parquet(PARQUET_PATH)
    
    # The parquet contains lat_grid, lon_grid, normal_frp_median, etc.
    # We will treat each unique lat_grid/lon_grid as a "facility"
    
    print(f"Loaded {len(df)} rows. Filtering to unique locations...")
    unique_facilities = df.drop_duplicates(subset=['lat_grid', 'lon_grid'])
    
    print(f"Found {len(unique_facilities)} unique facility locations.")
    
    with SessionLocal() as db:
        print("Truncating facilities table...")
        db.execute(text("TRUNCATE TABLE facilities CASCADE"))
        db.commit()
        
        print("Inserting facilities into PostGIS (this may take a minute)...")
        inserted = 0
        
        # Batch insert using raw SQL for speed
        values = []
        for _, row in unique_facilities.iterrows():
            lat = row['lat_grid']
            lon = row['lon_grid']
            name = f"FAC_{lat:.3f}_{lon:.3f}"
            
            # We use ST_SetSRID(ST_MakePoint(lon, lat), 4326)
            values.append({
                "name": name,
                "facility_type": "industrial",
                "lat": float(lat),
                "lon": float(lon)
            })
            
            if len(values) >= 5000:
                _insert_batch(db, values)
                db.commit()
                inserted += len(values)
                print(f"Inserted {inserted}...")
                values = []
                
        if values:
            _insert_batch(db, values)
            db.commit()
            inserted += len(values)
            
        print(f"Successfully seeded {inserted} facilities into Neon PostGIS!")

def _insert_batch(db, values):
    sql = text("""
        INSERT INTO facilities (name, facility_type, geometry)
        VALUES (:name, :facility_type, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
    """)
    db.execute(sql, values)

if __name__ == "__main__":
    seed_database()
