import logging
from pathlib import Path
from typing import Optional
import rasterio

LOGGER = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
LANDCOVER_TIFF_PATH = DATA_DIR / "landcover_india.tif"

# Mapping of raster pixel values to semantic categories (example for ESA WorldCover)
# 10: Tree cover, 20: Shrubland, 30: Grassland, 40: Cropland, 50: Built-up/Urban
LANDCOVER_CLASSES = {
    10: "forest",
    20: "shrubland",
    30: "grassland",
    40: "cropland",
    50: "urban",
    60: "bare_vegetation",
    70: "snow",
    80: "water",
    90: "wetland",
    100: "mangroves"
}

_dataset = None

def _get_dataset():
    global _dataset
    if _dataset is None:
        if not LANDCOVER_TIFF_PATH.exists():
            return None
        try:
            _dataset = rasterio.open(LANDCOVER_TIFF_PATH)
            LOGGER.info("Successfully loaded Landcover Raster %s", LANDCOVER_TIFF_PATH)
        except Exception as e:
            LOGGER.error("Failed to load Landcover Raster: %s", e)
    return _dataset

def get_landcover_class(lat: float, lon: float) -> Optional[str]:
    """
    Given a latitude and longitude, sample the Landcover GeoTIFF and return the semantic class (e.g., 'urban', 'cropland').
    """
    ds = _get_dataset()
    if ds is None:
        return None
        
    try:
        # Convert lat/lon to row/col in the raster
        # Note: Depending on the GeoTIFF's CRS, we might need pyproj to transform 
        # the WGS84 (lat/lon) into the raster's native coordinate system first.
        # Assuming the GeoTIFF is in EPSG:4326 for this MVP:
        row, col = ds.index(lon, lat)
        
        # Read the exact pixel value at that row/col
        # Window of 1x1 to read just that pixel
        window = rasterio.windows.Window(col_off=col, row_off=row, width=1, height=1)
        data = ds.read(1, window=window)
        
        if data.size > 0:
            pixel_value = int(data[0][0])
            return LANDCOVER_CLASSES.get(pixel_value, "unknown")
            
    except Exception as e:
        LOGGER.warning(f"Failed to sample landcover at {lat}, {lon}: {e}")
        
    return None
