# ThermoLens — Backend

Geospatial industrial-fire classification backend system. ThermoLens ingests satellite thermal anomaly feeds (NASA FIRMS / VIIRS / MODIS), enriches detections with contextual infrastructure proximity and landcover data, classifies heat signatures (distinguishing industrial operations and gas flares from wildfires and agricultural burns), and serves geospatial data over a REST API to the Next.js frontend.

---

## Module Ownership & Team Architecture

ThermoLens backend is organized into four modular domains, designed for parallel development across four engineers:

| Module | Folder | Owner | Core Responsibilities |
| :--- | :--- | :--- | :--- |
| **Ingestion** | `ingestion/` | Engineer 1 | NASA FIRMS API polling, raw CSV/JSON/GeoJSON ingestion, and initial DB ingestion. |
| **Enrichment** | `enrichment/` | Engineer 2 | PostGIS spatial queries, nearest facility distance calculations, landcover raster intersection, and temporal persistence tracking. |
| **Classification** | `classification/` | Engineer 3 | ML classification models (industrial, gas flare, agricultural burn, mining, wildfire), confidence scoring, and inference pipeline. |
| **API & Delivery** | `api/` | Engineer 4 | FastAPI routes, GeoJSON FeatureCollections, spatial filters (bbox, date, class), and frontend integration. |

Supporting directories:
- `shared/`: Pydantic v2 schemas defining the contracts between all four modules.
- `db/`: SQLAlchemy 2.x models with GeoAlchemy2 PostGIS geometry types, session factories, and Alembic migrations.
- `data/`: Local directory for sample GeoTIFFs, raster datasets, and GeoJSON files (gitignored).
- `notebooks/`: Exploratory data analysis, prototyping, and model evaluation notebooks.
- `tests/`: Automated pytest suite.

---

## Tech Stack

- **Python**: 3.11+ (managed via local virtual environment)
- **API Framework**: FastAPI + Uvicorn
- **Database**: PostgreSQL 16 with PostGIS extension (installed locally per machine)
- **ORM & DB Toolkit**: SQLAlchemy 2.x + GeoAlchemy2
- **Migrations**: Alembic
- **Data Validation & Contracts**: Pydantic v2
- **Geospatial & Raster Stack**: GeoPandas, Shapely, Rasterio, HTTPX

---

## Getting Started

### 1. Clone & Set Up Python Virtual Environment

```bash
# Clone the repository
git clone https://github.com/your-org/thermolens-backend.git
cd thermolens-backend

# Create a virtual environment with Python 3.11+
python -m venv venv

# Activate the virtual environment:
# On macOS / Linux:
source venv/bin/activate

# On Windows (PowerShell):
venv\Scripts\Activate.ps1
# On Windows (Command Prompt):
venv\Scripts\activate.bat

# Upgrade pip and install all dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 🐘 Local PostgreSQL & PostGIS Setup

> **Important**: ThermoLens does **not** use Docker. Each teammate runs PostgreSQL 16 with the PostGIS extension locally. Because usernames, passwords, and ports will vary per operating system and developer machine, your `.env` file is local and must **never** be committed (`DATABASE_URL` will differ per machine — that's expected and fine for local dev).

### Installation by Operating System

#### 🍎 macOS (Homebrew)
```bash
brew install postgresql@16 postgis
brew services start postgresql@16
```

#### 🐧 Ubuntu / Debian
```bash
sudo apt update
sudo apt install postgresql-16 postgresql-16-postgis-3
sudo systemctl start postgresql
```

#### 🪟 Windows
1. Download and install PostgreSQL 16 from [EnterpriseDB](https://www.enterprisedb.com/downloads/postgres-postgresql-downloads).
2. At the end of installation, run **Stack Builder** or download the PostGIS bundle installer directly from [postgis.net/install](https://postgis.net/install/).

---

### Database Creation & Extension Setup

Once PostgreSQL is installed and running, create the `thermolens` database and activate PostGIS:

```bash
# Create the database
createdb thermolens

# Enable the PostGIS spatial extension
psql thermolens -c "CREATE EXTENSION postgis;"
```

Verify PostGIS is installed:
```bash
psql thermolens -c "SELECT PostGIS_Version();"
```

---

## ⚙️ Environment Configuration

Copy the sample environment file to `.env`:
```bash
cp .env.example .env
```

Edit `.env` to match your local PostgreSQL credentials:
```env
# Example for macOS / default local postgres
DATABASE_URL=postgresql://localhost:5432/thermolens

# Example for Postgres with user/password
# DATABASE_URL=postgresql://postgres:yourpassword@localhost:5432/thermolens

# NASA FIRMS API Key (placeholder for ingestion module)
FIRMS_API_KEY=your_firms_api_key_here
```

---

## 🗄️ Database Migrations

Alembic manages all schema changes for `facilities`, `hotspots`, and `classified_hotspots`.
```bash
# Apply migrations to your local database
alembic upgrade head

# To revert the migration if needed:
alembic downgrade -1
```

---

## 🌐 Running the API

Start the FastAPI development server with hot-reload:
```bash
uvicorn api.main:app --reload
```

The server will start at `http://127.0.0.1:8000`.

### Interactive API Documentation
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

---

## 🧪 Verification & Health Check

Once your local PostgreSQL 16 is running and migrations are applied, verify the system status:
```bash
curl http://localhost:8000/health
```

Expected response when PostgreSQL & PostGIS are connected:
```json
{
  "status": "ok",
  "database": "connected",
  "postgis_version": "3.4.2 ...",
  "message": "ThermoLens backend is operational."
}
```

If the database is unreachable or `DATABASE_URL` is misconfigured, the health endpoint returns a descriptive HTTP 503 message indicating the exact connection error and troubleshooting steps.

---

## API Endpoints Summary

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | [/](file:///C:/Users/ponma/thermo-lens-backend/api/main.py) | API service metadata and documentation links |
| `GET` | [/health](file:///C:/Users/ponma/thermo-lens-backend/api/main.py) | Health probe validating database and PostGIS extension connectivity |
| `GET` | [/hotspots](file:///C:/Users/ponma/thermo-lens-backend/api/main.py) | Query thermal anomalies with `bbox`, `start_date`, `end_date`, `class` filters |
| `GET` | [/facilities](file:///C:/Users/ponma/thermo-lens-backend/api/main.py) | Query industrial facilities with `facility_type`, `bbox` filters |

---

## Azure Container Apps Deployment

The Azure deployment uses one 2 vCPU / 4 GiB Container Apps replica and stores
`factory_roster_2yr.parquet` in a private Azure Blob Storage container. The app
uses its system-assigned managed identity to read the roster, so no storage key
is stored in the application configuration.

Install the [Azure CLI](https://aka.ms/installazurecliwindows), sign in with
`az login`, then run the following from PowerShell:

```powershell
.\azure\deploy.ps1 -DatabaseUrl "postgresql://USER:PASSWORD@HOST:5432/DATABASE"
```

Optional arguments let you select a region, resource group, application name,
and FIRMS API key:

```powershell
.\azure\deploy.ps1 `
  -DatabaseUrl "postgresql://USER:PASSWORD@HOST:5432/DATABASE" `
  -Location "centralindia" `
  -ResourceGroup "thermolens-rg" `
  -AppName "thermolens-api" `
  -FirmsApiKey "YOUR_FIRMS_KEY"
```

The script uploads the local `data/factory_roster_2yr.parquet`, creates the
Container App, grants it `Storage Blob Data Reader`, and prints the public API
URL. It creates resources in the specified resource group; delete that resource
group from Azure when you no longer want to incur charges.
