"""Retrieve and validate the factory roster before the spatial cache starts."""

import logging
import os
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.request import urlopen

import pyarrow.parquet as pq

LOGGER = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
PARQUET_PATH = DATA_DIR / "factory_roster_2yr.parquet"
DEFAULT_ROSTER_URL = (
    "https://github.com/itsayushch/thermo-lens-backend/releases/download/"
    "data_v1/factory_roster_2yr.parquet"
)


def _is_valid_parquet(path: Path) -> bool:
    try:
        return pq.ParquetFile(path).metadata.num_rows > 0
    except Exception:
        return False


def _download_from_blob(destination: Path) -> None:
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobClient

    account_url = os.environ["AZURE_STORAGE_ACCOUNT_URL"]
    container = os.getenv("AZURE_ROSTER_CONTAINER", "datasets")
    blob_name = os.getenv("AZURE_ROSTER_BLOB", "factory_roster_2yr.parquet")
    client = BlobClient(
        account_url=account_url,
        container_name=container,
        blob_name=blob_name,
        credential=DefaultAzureCredential(),
    )

    with destination.open("wb") as stream:
        client.download_blob(max_concurrency=4).readinto(stream)


def _download_from_url(destination: Path) -> None:
    roster_url = os.getenv("FACTORY_ROSTER_URL", DEFAULT_ROSTER_URL)
    with urlopen(roster_url, timeout=120) as response, destination.open("wb") as stream:
        while chunk := response.read(1024 * 1024):
            stream.write(chunk)


def ensure_factory_roster() -> Path:
    """Ensure a valid roster exists, preferring Azure Blob Storage when configured."""
    if _is_valid_parquet(PARQUET_PATH):
        LOGGER.info("Factory roster is already present and valid.")
        return PARQUET_PATH

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    use_azure_blob = bool(os.getenv("AZURE_STORAGE_ACCOUNT_URL"))
    source = "Azure Blob Storage" if use_azure_blob else "the configured roster URL"
    LOGGER.info("Downloading factory roster from %s.", source)

    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            with NamedTemporaryFile(dir=DATA_DIR, suffix=".parquet", delete=False) as stream:
                temporary_path = Path(stream.name)
            try:
                if use_azure_blob:
                    _download_from_blob(temporary_path)
                else:
                    _download_from_url(temporary_path)

                if not _is_valid_parquet(temporary_path):
                    raise ValueError("Downloaded factory roster is not a valid parquet file.")
                temporary_path.replace(PARQUET_PATH)
                LOGGER.info("Factory roster downloaded and validated.")
                return PARQUET_PATH
            finally:
                temporary_path.unlink(missing_ok=True)
        except Exception as exc:
            last_error = exc
            LOGGER.warning("Factory roster download attempt %s/5 failed: %s", attempt, exc)
            if attempt < 5:
                time.sleep(attempt * 2)

    raise RuntimeError("Unable to download a valid factory roster.") from last_error
