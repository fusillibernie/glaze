"""Download Glazy open data and convert to compact JSON for the community recipes feature.

Run this once to populate data/glazy_bulk/glazy_recipes.json.
Data source: https://github.com/derekphilipau/glazy-data (CC BY-NC-SA 4.0)
"""

import gzip
import json
import shutil
import urllib.request
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data" / "glazy_bulk"
YAML_URL = "https://raw.githubusercontent.com/derekphilipau/glazy-data/master/glazy-20260227.yaml.gz"
OUTPUT_FILE = DATA_DIR / "glazy_recipes.json"


def download_and_convert():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if OUTPUT_FILE.exists():
        print(f"Data already exists at {OUTPUT_FILE} ({OUTPUT_FILE.stat().st_size / 1024 / 1024:.1f} MB)")
        resp = input("Re-download? [y/N] ").strip().lower()
        if resp != "y":
            return

    gz_path = DATA_DIR / "glazy-20260227.yaml.gz"

    # Download
    print(f"Downloading {YAML_URL}...")
    urllib.request.urlretrieve(YAML_URL, gz_path)
    print(f"Downloaded {gz_path.stat().st_size / 1024 / 1024:.1f} MB")

    # Decompress
    yaml_path = DATA_DIR / "glazy-20260227.yaml"
    print("Decompressing...")
    with gzip.open(gz_path, "rb") as f_in, open(yaml_path, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)

    # Parse YAML
    print("Parsing YAML (this takes a moment)...")
    import yaml

    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    print(f"Loaded {len(data)} entries")

    # Extract glaze recipes
    glazes = []
    for entry in data:
        subtype = entry.get("Subtype", "")
        if not subtype.startswith("Glaze"):
            continue
        ings = entry.get("Ingredients", [])
        if not ings:
            continue
        analysis = entry.get("Percent Analysis", {})
        if not analysis:
            continue

        atm = entry.get("Atmospheres", [])
        if isinstance(atm, str):
            atm = [atm]

        glazes.append(
            {
                "id": entry.get("ID"),
                "name": entry.get("Name", ""),
                "cone": entry.get("Cone", ""),
                "surface": entry.get("Surface", ""),
                "atmospheres": atm or [],
                "subtype": subtype,
                "description": (entry.get("Description") or "")[:200],
                "ingredients": [
                    {"name": i["Name"], "pct": i["Percentage"], "add": i.get("Additional", False)}
                    for i in ings
                    if i.get("Name") and i.get("Percentage")
                ],
                "analysis": {k: round(v, 2) for k, v in analysis.items() if v and v > 0},
            }
        )

    print(f"Extracted {len(glazes)} glaze recipes")

    # Save compact JSON
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(glazes, f, separators=(",", ":"))

    size_mb = OUTPUT_FILE.stat().st_size / 1024 / 1024
    print(f"Saved to {OUTPUT_FILE} ({size_mb:.1f} MB)")

    # Clean up
    yaml_path.unlink(missing_ok=True)
    gz_path.unlink(missing_ok=True)
    print("Cleaned up temporary files. Done!")


if __name__ == "__main__":
    download_and_convert()
