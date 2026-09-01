import geopandas as gpd

file_path = "india-260824.osm.pbf"

print("Scanning polygon layers safely in chunks...")

# Instead of loading everything into RAM at once, we use
# a bounding box or chunk-reading parameters if supported,
# or read only rows in batches using pyogrio engine.
# Let's read the polygon layer using a bbox filter for a specific region
# (e.g., around your coordinates/state area) so it only loads a tiny fraction of India.

# Bounding box format for pyogrio/geopandas: (xmin, ymin, xmax, ymax)
# This example box roughly covers the Andhra Pradesh region:
# [min_lon, min_lat, max_lon, max_lat]
ap_bbox = (77.0, 12.5, 85.0, 20.0)

print("Loading localized polygon slice...")
gdf = gpd.read_file(file_path, layer="multipolygons", bbox=ap_bbox)

print(f"Success! Loaded {len(gdf)} localized zones instead of millions.")

# Extract tags safely
if 'landuse' in gdf.columns:
    unique_landuse = gdf['landuse'].dropna().unique()
    print("\n--- LANDUSE ZONES FOUND IN REGION ---")
    for tag in sorted(unique_landuse):
        print(tag)

if 'natural' in gdf.columns:
    unique_natural = gdf['natural'].dropna().unique()
    print("\n--- NATURAL ZONES FOUND IN REGION ---")
    for tag in sorted(unique_natural):
        print(tag)

# Save this small region instantly so you never have to parse the 1.6GB file again
output_file = "local_threat_zones.geojson"
gdf.to_file(output_file, driver="GeoJSON")
print(f"\nSaved lightweight regional file to {output_file}!")