# Glaze Formulator

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/fusillibernie/glaze?quickstart=1)
[![Open in Gitpod](https://gitpod.io/button/open-in-gitpod.svg)](https://gitpod.io/#https://github.com/fusillibernie/glaze)

> **Try it now** -- Click either badge above to launch the app in your browser. No install needed. The server starts automatically and opens the UI on port 8000.

A ceramic glaze formulation and analysis tool that uses data from Glazy.org, scientific research, and literature to help create and predict ceramic glaze outcomes.

## Features

### Core Functionality

- **UMF Calculations**: Calculate Unity Molecular Formula from recipe percentages
- **Stull Chart Analysis**: Predict glaze surface (glossy, satin, matte) based on Si:Al ratios
- **Chemistry Analysis**: Identify issues, warnings, and recommendations
- **Outcome Prediction**: Predict colors, surfaces, and defect risks
- **Thermal Expansion**: Analyze crazing and shivering risks
- **Photo Documentation**: Upload and track firing results

### Classification & Search (Like Glazy.org)

- **Stull Region Classification**: Automatically categorize glazes by position on Stull chart
- **Unified Categories**: Glazes grouped by composition (celadon, tenmoku, shino, etc.)
- **Similarity Search**: Find glazes with similar chemistry
- **Flux Profile Search**: Filter by alkali-dominant, zinc, boron content
- **UMF Range Search**: Find glazes within specific oxide ranges
- **Food Safety Warnings**: Automatic lead/barium detection

### Cone Support

- **Cone 6** (~1222°C / 2232°F) - Mid-fire oxidation
- **Cone 10** (~1305°C / 2381°F) - High-fire reduction

### Firing Atmospheres

- Oxidation (electric kilns)
- Reduction (gas kilns)
- Wood firing
- Salt/soda firing

### Clay Bodies

- Stoneware
- Porcelain
- Earthenware
- B-Mix and others

## Installation

```bash
pip install -e .
```

### Dependencies

```bash
pip install fastapi uvicorn httpx pydantic
```

## Usage

### Start the API Server

```bash
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

### API Documentation

Once running, visit:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## API Endpoints

### Materials

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/materials` | GET | List all materials |
| `/api/materials/{name}` | GET | Get material details |
| `/api/materials/{name}/substitutes` | GET | Find substitute materials |

### Recipes

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/recipes/calculate-umf` | POST | Calculate UMF for a recipe |
| `/api/recipes/analyze` | POST | Full chemistry analysis |
| `/api/recipes/predict` | POST | Predict firing outcome |
| `/api/recipes/formulate` | POST | Generate recipe from target UMF |
| `/api/recipes/add-colorant` | POST | Add colorant to recipe |

### Classification & Search

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/classify` | POST | Classify a recipe by Stull position |
| `/api/search/by-region/{region}` | GET | Find glazes in a Stull region |
| `/api/search/by-category/{category}` | GET | Find glazes by category |
| `/api/search/similar` | POST | Find similar glazes |
| `/api/search/by-umf` | GET | Search by UMF ranges |
| `/api/search/by-flux` | GET | Search by flux profile |
| `/api/classify/statistics` | GET | Get classification statistics |
| `/api/reference/stull-regions` | GET | List Stull regions |
| `/api/reference/glaze-categories` | GET | List glaze categories |

### Glazy.org Integration

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/glazy/search` | GET | Search Glazy recipes |
| `/api/glazy/recipe/{id}` | GET | Fetch recipe from Glazy |
| `/api/glazy/material/{id}` | GET | Fetch material from Glazy |

### Results & Photos

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/results` | GET | List firing results |
| `/api/results` | POST | Submit firing result |
| `/api/results/upload-photo` | POST | Upload result photo |

### Reference Data

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/reference/cones` | GET | List cone temperatures |
| `/api/reference/atmospheres` | GET | List firing atmospheres |
| `/api/reference/clay-bodies` | GET | List clay body types |
| `/api/reference/umf-ranges/{cone}` | GET | Get UMF ranges for cone |

## Example: Analyze a Recipe

```python
import httpx

recipe = {
    "name": "Leach 4321",
    "ingredients": [
        {"material_name": "Custer Feldspar", "percentage": 40.0},
        {"material_name": "Silica (Flint)", "percentage": 30.0},
        {"material_name": "Whiting (Calcium Carbonate)", "percentage": 20.0},
        {"material_name": "EPK Kaolin", "percentage": 10.0}
    ],
    "target_cone": "10",
    "atmospheres": ["reduction"]
}

response = httpx.post("http://localhost:8000/api/recipes/analyze", json=recipe)
analysis = response.json()

print(f"Predicted Surface: {analysis['predicted_surface']}")
print(f"Si:Al Ratio: {analysis['umf']['silica_alumina_ratio']}")
print(f"Issues: {analysis['issues']}")
print(f"Recommendations: {analysis['recommendations']}")
```

## Example: Predict Outcome

```python
recipe = {
    "name": "Floating Blue",
    "ingredients": [
        {"material_name": "Nepheline Syenite", "percentage": 47.0},
        {"material_name": "Silica (Flint)", "percentage": 20.0},
        {"material_name": "Frit 3134", "percentage": 15.0},
        {"material_name": "EPK Kaolin", "percentage": 10.0},
        {"material_name": "Dolomite", "percentage": 4.0},
        {"material_name": "Bone Ash", "percentage": 4.0}
    ],
    "colorants": [
        {"material_name": "Rutile", "percentage": 4.0},
        {"material_name": "Cobalt Carbonate", "percentage": 1.0}
    ],
    "target_cone": "6"
}

firing = {
    "cone": "6",
    "atmosphere": "oxidation",
    "firing_type": "electric"
}

response = httpx.post(
    "http://localhost:8000/api/recipes/predict",
    json=recipe,
    params={"clay_body": "stoneware", "firing": firing}
)

prediction = response.json()
print(f"Predicted Surface: {prediction['predicted_surface']}")
print(f"Predicted Color: {prediction['predicted_color']}")
print(f"Defect Risks: {prediction['defect_risks']}")
```

## Project Structure

```
glaze/
├── src/
│   ├── models/
│   │   ├── materials.py    # Material definitions, oxide analysis
│   │   ├── umf.py          # Unity Molecular Formula, Stull chart
│   │   ├── glaze.py        # Recipes, ingredients, firing schedules
│   │   └── results.py      # Firing results, photo uploads
│   ├── services/
│   │   ├── materials_db.py # Materials database
│   │   ├── formulator.py   # Recipe formulation
│   │   ├── analyzer.py     # Chemistry analysis
│   │   ├── predictor.py    # Outcome prediction
│   │   └── classifier.py   # Stull-based classification & search
│   └── integrations/
│       └── glazy_client.py # Glazy.org API client
├── api/
│   └── main.py             # FastAPI application
├── data/
│   ├── materials/          # Material definitions (JSON)
│   ├── recipes/            # Base glaze recipes (JSON)
│   ├── glazy_cache/        # Cached Glazy.org data
│   └── uploads/            # Uploaded photos
└── tests/
    ├── test_umf.py
    ├── test_formulator.py
    ├── test_analyzer.py
    └── test_api.py
```

## Key Concepts

### Unity Molecular Formula (UMF)

The UMF normalizes glaze chemistry so fluxes sum to 1.0. This allows comparing glazes regardless of raw materials used.

**Typical Cone 6 UMF Ranges:**
- SiO2: 2.5 - 4.5
- Al2O3: 0.2 - 0.5
- Flux Total: 1.0

**Typical Cone 10 UMF Ranges:**
- SiO2: 3.0 - 5.0
- Al2O3: 0.3 - 0.6
- Flux Total: 1.0

### Stull Chart

The Stull Chart maps Al2O3 vs SiO2 to predict glaze surfaces:

| Si:Al Ratio | Surface |
|-------------|---------|
| > 12 | Glossy (may run) |
| 8 - 12 | Glossy |
| 6 - 8 | Satin |
| < 6 | Matte |

### Stull Regions

The classifier automatically categorizes glazes into these regions:

| Region | Description |
|--------|-------------|
| `glossy` | Si:Al 8-12, typical glossy glaze |
| `satin` | Si:Al 6-8, semi-matte |
| `matte` | Si:Al < 6, true matte |
| `dry_matte` | High alumina (> 0.45), can be too dry |
| `runny` | Si:Al > 12, may run |
| `crystalline_zone` | Low Al2O3 with zinc, favorable for crystals |

### Glaze Categories

Glazes are classified by their characteristic style:

| Category | Description |
|----------|-------------|
| `celadon` | Iron reduction glazes, jade-like |
| `tenmoku` | High iron, dark brown/black |
| `shino` | Thick, orange-flashing glazes |
| `ash_glaze` | Wood or plant ash based |
| `crystalline` | Crystal-growing glazes |
| `rutile_blue` | Titanium-based breaking blues |
| `clear_glossy` | Transparent glossy bases |
| `colored_glossy` | Colored glossy glazes |
| `satin_matte` | Semi-matte surfaces |
| `true_matte` | Full matte glazes |

### Defect Prediction

| Defect | Common Causes |
|--------|--------------|
| Crawling | High alumina, thick application, dusty bisque |
| Crazing | High alkali flux, thermal expansion mismatch |
| Running | Low alumina, too thick application |
| Pinholing | Fast cooling, high boron, gassy clay |

## Included Base Glazes

The `data/recipes/base_glazes.json` includes classic recipes:

- **Leach 4321** - Cone 10 reduction, celadon/tenmoku base
- **Pinnell Clear** - Cone 6 oxidation, versatile clear
- **Floating Blue** - Cone 6, breaking blue
- **Val's Turquoise** - Cone 6, copper turquoise
- **Dolomite Matte** - Cone 10 reduction, buttery matte
- **Shino** - Cone 10, carbon trap shino

## Running Tests

```bash
pytest tests/ -v
```

## Data Sources

- [Glazy.org](https://glazy.org) - Community glaze database
- Stull Chart - H.V. Stull (1912)
- Ceramic literature and research

## Contributing

1. Add materials to `data/materials/`
2. Add recipes to `data/recipes/`
3. Submit firing results via API
4. Upload photos of results

## License

MIT License
