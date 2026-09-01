import geopandas as gpd

file_path = "export.geojson"

print("Loading GeoJSON polygon boundaries...")
# Remove layer="multipolygons" because GeoJSON reads directly
gdf = gpd.read_file(file_path)

print("\n--- AVAILABLE COLUMNS IN YOUR DATASET ---")
print(list(gdf.columns))

# Check for landuse tags
if 'landuse' in gdf.columns:
    unique_landuse = gdf['landuse'].dropna().unique()
    print("\n--- ALL LANDUSE ZONES FOUND ---")
    for tag in sorted(unique_landuse):
        print(tag)