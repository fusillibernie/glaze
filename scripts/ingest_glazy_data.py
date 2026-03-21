"""Ingest Glazy public data repository into local JSON format.

Downloads and parses CSV data from https://github.com/derekphilipau/glazy-data
into the app's recipe and material JSON format.

Usage:
    python scripts/ingest_glazy_data.py [--csv-path PATH]

If --csv-path is not provided, downloads the latest CSV from GitHub.
"""

import argparse
import csv
import gzip
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    import httpx
except ImportError:
    httpx = None


GLAZY_DATA_REPO = "https://github.com/derekphilipau/glazy-data"
# CSV files from the repo (composites = recipes only)
GLAZY_CSV_URL = (
    "https://raw.githubusercontent.com/derekphilipau/glazy-data/master/"
    "glazy-data-glazes-20260227.csv"
)
GLAZY_ALL_CSV_URL = (
    "https://raw.githubusercontent.com/derekphilipau/glazy-data/master/"
    "glazy-data-all-20260227.csv"
)

DATA_DIR = Path(__file__).parent.parent / "data"
OUTPUT_DIR = DATA_DIR / "glazy_bulk"

# Oxide fields in the CSV (percent analysis)
OXIDE_FIELDS = [
    "SiO2", "Al2O3", "B2O3", "Li2O", "K2O", "Na2O",
    "KNaO", "CaO", "MgO", "BaO", "SrO", "ZnO",
    "Fe2O3", "MnO2", "P2O5", "TiO2", "ZrO2", "SnO2",
    "V2O5", "Cr2O3", "CoO", "CuO", "NiO",
]

# Surface type mapping (Glazy uses numeric IDs)
SURFACE_MAP = {
    "1": "matte",
    "2": "matte",  # near-matte
    "3": "satin",
    "4": "satin",  # near-satin
    "5": "glossy",
    "6": "glossy",  # near-glossy
    "7": "glossy",  # bright glossy
    "8": "glossy",  # mirror
    "9": "matte",   # dry matte
}

# Transparency type mapping
TRANSPARENCY_MAP = {
    "1": "opaque",
    "2": "translucent",
    "3": "transparent",
    "4": "transparent",  # clear
}


def download_csv(url: str) -> str:
    """Download CSV content from URL."""
    if httpx is None:
        print("httpx not installed. Use --csv-path to provide a local file.")
        sys.exit(1)

    print(f"Downloading from {url}...")
    client = httpx.Client(timeout=120.0, follow_redirects=True)
    response = client.get(url)
    response.raise_for_status()
    print(f"Downloaded {len(response.content)} bytes")
    return response.text


def parse_cone(from_cone: str, to_cone: str) -> Optional[str]:
    """Parse cone range into a single cone value."""
    if from_cone and to_cone:
        if from_cone == to_cone:
            return from_cone
        return f"{from_cone}-{to_cone}"
    return from_cone or to_cone or None


def parse_atmosphere(atm_str: str) -> Optional[str]:
    """Parse atmosphere string from Glazy data."""
    if not atm_str:
        return None
    atm_lower = atm_str.strip().lower()
    mapping = {
        "oxidation": "oxidation",
        "reduction": "reduction",
        "neutral": "neutral",
        "wood": "wood",
        "salt": "salt",
        "soda": "soda",
    }
    for key, value in mapping.items():
        if key in atm_lower:
            return value
    return atm_lower


def parse_csv_row(row: dict) -> Optional[dict]:
    """Parse a single CSV row into our recipe format."""
    name = row.get("name", "").strip()
    if not name:
        return None

    # Skip private, theoretical, or primitive entries
    if row.get("is_private") == "1":
        return None
    if row.get("is_theoretical") == "1":
        return None

    glazy_id = row.get("id", "")
    material_type = row.get("material_type", "").lower()

    # Determine if this is a recipe/glaze vs raw material
    is_recipe = "recipe" in material_type or "glaze" in material_type

    # Parse cone
    cone = parse_cone(
        row.get("from_orton_cone", ""),
        row.get("to_orton_cone", ""),
    )

    # Parse surface
    surface_id = row.get("surface_type", "")
    surface = SURFACE_MAP.get(str(surface_id), None)

    # Parse atmosphere - could be in material_type_concatenated
    atmosphere = None
    type_concat = row.get("material_type_concatenated", "")
    if "oxidation" in type_concat.lower():
        atmosphere = "oxidation"
    elif "reduction" in type_concat.lower():
        atmosphere = "reduction"
    elif "wood" in type_concat.lower():
        atmosphere = "wood"
    elif "salt" in type_concat.lower():
        atmosphere = "salt"
    elif "soda" in type_concat.lower():
        atmosphere = "soda"

    # Parse oxide analysis (percent)
    percent_analysis = {}
    for oxide in OXIDE_FIELDS:
        key = f"{oxide}_percent"
        val = row.get(key, "")
        if val:
            try:
                fval = float(val)
                if fval > 0:
                    percent_analysis[oxide] = round(fval, 4)
            except (ValueError, TypeError):
                pass

    # Parse UMF analysis
    umf_analysis = {}
    for oxide in OXIDE_FIELDS:
        key = f"{oxide}_umf"
        val = row.get(key, "")
        if val:
            try:
                fval = float(val)
                if fval > 0:
                    umf_analysis[oxide] = round(fval, 4)
            except (ValueError, TypeError):
                pass

    # Parse Si:Al ratio
    si_al_ratio = None
    ratio_val = row.get("SiO2_Al2O3_ratio_umf", "")
    if ratio_val:
        try:
            si_al_ratio = round(float(ratio_val), 2)
        except (ValueError, TypeError):
            pass

    # Parse RGB color
    rgb = None
    r, g, b = row.get("rgb_r", ""), row.get("rgb_g", ""), row.get("rgb_b", "")
    if r and g and b:
        try:
            rgb = [int(float(r)), int(float(g)), int(float(b))]
        except (ValueError, TypeError):
            pass

    # Parse subtype for categorization
    subtype = row.get("material_type_concatenated", "")

    # Build record
    record = {
        "glazy_id": int(glazy_id) if glazy_id else None,
        "name": name,
        "source": "glazy-data",
        "is_recipe": is_recipe,
        "subtype": subtype,
    }

    if cone:
        record["cone"] = cone
    if surface:
        record["surface"] = surface
    if atmosphere:
        record["atmosphere"] = atmosphere
    if percent_analysis:
        record["percent_analysis"] = percent_analysis
    if umf_analysis:
        record["umf_analysis"] = umf_analysis
    if si_al_ratio:
        record["si_al_ratio"] = si_al_ratio
    if rgb:
        record["rgb"] = rgb

    # Description
    desc = row.get("description", "").strip()
    if desc:
        record["description"] = desc

    # Creator
    creator = row.get("created_by_user_id", "")
    if creator:
        record["creator_id"] = creator

    # Transparency
    trans_id = row.get("transparency_type", "")
    if trans_id and str(trans_id) in TRANSPARENCY_MAP:
        record["transparency"] = TRANSPARENCY_MAP[str(trans_id)]

    return record


def ingest_csv(csv_content: str) -> tuple[list[dict], list[dict]]:
    """Parse CSV content into recipes and materials lists."""
    reader = csv.DictReader(io.StringIO(csv_content))

    recipes = []
    materials = []
    skipped = 0

    for row in reader:
        record = parse_csv_row(row)
        if record is None:
            skipped += 1
            continue

        if record.get("is_recipe"):
            del record["is_recipe"]
            recipes.append(record)
        else:
            del record["is_recipe"]
            materials.append(record)

    return recipes, materials


def save_output(recipes: list[dict], materials: list[dict]) -> None:
    """Save parsed data to JSON files."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Save recipes
    recipes_path = OUTPUT_DIR / "recipes.json"
    with open(recipes_path, "w", encoding="utf-8") as f:
        json.dump({"source": "glazy-data", "recipes": recipes}, f, indent=2)
    print(f"Saved {len(recipes)} recipes to {recipes_path}")

    # Save materials
    materials_path = OUTPUT_DIR / "materials.json"
    with open(materials_path, "w", encoding="utf-8") as f:
        json.dump({"source": "glazy-data", "materials": materials}, f, indent=2)
    print(f"Saved {len(materials)} materials to {materials_path}")

    # Save metadata
    metadata = {
        "source": GLAZY_DATA_REPO,
        "license": "CC BY-NC-SA 4.0",
        "attribution": "Data from Glazy.org public data repository by Derek Philipau",
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "recipe_count": len(recipes),
        "material_count": len(materials),
    }
    metadata_path = OUTPUT_DIR / ".metadata.json"
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
    print(f"Saved metadata to {metadata_path}")


def main():
    parser = argparse.ArgumentParser(description="Ingest Glazy public data")
    parser.add_argument(
        "--csv-path",
        type=Path,
        help="Path to local CSV file (skips download)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Download all data (materials + recipes), not just glazes",
    )
    args = parser.parse_args()

    if args.csv_path:
        print(f"Reading from {args.csv_path}...")
        csv_content = args.csv_path.read_text(encoding="utf-8")
    else:
        url = GLAZY_ALL_CSV_URL if args.all else GLAZY_CSV_URL
        csv_content = download_csv(url)

    recipes, materials = ingest_csv(csv_content)

    print(f"\nParsed {len(recipes)} recipes, {len(materials)} materials")

    # Show some stats
    cones = {}
    surfaces = {}
    for r in recipes:
        c = r.get("cone", "unknown")
        s = r.get("surface", "unknown")
        cones[c] = cones.get(c, 0) + 1
        surfaces[s] = surfaces.get(s, 0) + 1

    print("\nCone distribution:")
    for cone, count in sorted(cones.items(), key=lambda x: -x[1])[:10]:
        print(f"  Cone {cone}: {count}")

    print("\nSurface distribution:")
    for surface, count in sorted(surfaces.items(), key=lambda x: -x[1]):
        print(f"  {surface}: {count}")

    save_output(recipes, materials)
    print("\nDone!")


if __name__ == "__main__":
    main()
