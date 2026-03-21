"""Parse John Sankey's Glaze Database into JSON format.

Source: https://johnsankey.ca/glazedata.html
Format: Field-coded text (A=name, B=source, C=cone, D=firing, E=ingredients, etc.)

Usage:
    python scripts/parse_sankey.py --input sankey_raw.txt
    python scripts/parse_sankey.py --download
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    import httpx
except ImportError:
    httpx = None

DATA_DIR = Path(__file__).parent.parent / "data"
OUTPUT_DIR = DATA_DIR / "sankey"

SANKEY_URL = "https://johnsankey.ca/glazedata.txt"

# Field codes used in Sankey's format
FIELD_CODES = {
    "A": "name",
    "B": "source",
    "C": "cone",
    "D": "firing",
    "E": "ingredients",
    "F": "surface",
    "G": "flaws",
    "H": "tester",
    "I": "notes",
    "J": "color",
    "K": "opacity",
}


def download_sankey() -> str:
    """Download Sankey database."""
    if httpx is None:
        print("httpx not installed.")
        sys.exit(1)

    print(f"Downloading from {SANKEY_URL}...")
    client = httpx.Client(timeout=60.0, follow_redirects=True)
    response = client.get(SANKEY_URL)
    response.raise_for_status()
    return response.text


def parse_ingredients(text: str) -> list[dict]:
    """Parse ingredient text into structured list.

    Examples:
        'Custer Feldspar 40, Silica 30, Whiting 20, EPK 10'
        'Nepheline Syenite 50 / Silica 25 / Whiting 15 / Kaolin 10'
    """
    ingredients = []
    # Split by comma or slash
    parts = re.split(r'[,/]', text)

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Try to extract name and percentage
        # Pattern: "Material Name 25" or "Material Name 25.5"
        match = re.match(r'^(.+?)\s+(\d+\.?\d*)\s*%?\s*$', part)
        if match:
            name = match.group(1).strip()
            pct = float(match.group(2))
            ingredients.append({"material": name, "percentage": pct})
        else:
            # Just a name with no percentage
            ingredients.append({"material": part, "percentage": 0})

    return ingredients


def parse_cone(text: str) -> Optional[str]:
    """Parse cone from text like 'Cone 6', 'C/6', '06-6'."""
    text = text.strip()
    # Match patterns like "6", "06", "Cone 6", "C/6", "6-10"
    match = re.search(r'(\d+)\s*[-–]\s*(\d+)', text)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    match = re.search(r'(\d+)', text)
    if match:
        return match.group(1)
    return text


def parse_atmosphere(text: str) -> Optional[str]:
    """Parse atmosphere from firing description."""
    text = text.lower()
    if "reduction" in text:
        return "reduction"
    if "oxidation" in text or "electric" in text:
        return "oxidation"
    if "wood" in text:
        return "wood"
    if "salt" in text:
        return "salt"
    if "soda" in text:
        return "soda"
    return None


def parse_surface(text: str) -> Optional[str]:
    """Parse surface type."""
    text = text.lower()
    if "gloss" in text:
        return "glossy"
    if "satin" in text:
        return "satin"
    if "matte" in text or "matt" in text:
        return "matte"
    return text.strip() if text.strip() else None


def parse_sankey_text(text: str) -> list[dict]:
    """Parse the full Sankey database text into recipe records."""
    recipes = []
    current_recipe = {}

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            # Empty line = end of record
            if current_recipe and current_recipe.get("name"):
                recipes.append(finalize_recipe(current_recipe))
                current_recipe = {}
            continue

        # Check for field code at start (single letter followed by colon or space)
        if len(line) >= 2 and line[0].isalpha() and line[1] in ":.= ":
            code = line[0].upper()
            value = line[2:].strip()
            field_name = FIELD_CODES.get(code)
            if field_name:
                current_recipe[field_name] = value
            else:
                # Unknown code, store as note
                current_recipe.setdefault("extra", []).append(line)
        elif current_recipe:
            # Continuation of previous field
            last_key = list(current_recipe.keys())[-1] if current_recipe else None
            if last_key and last_key != "extra":
                current_recipe[last_key] += " " + line

    # Don't forget last record
    if current_recipe and current_recipe.get("name"):
        recipes.append(finalize_recipe(current_recipe))

    return recipes


def finalize_recipe(raw: dict) -> dict:
    """Convert raw parsed fields into final recipe format."""
    recipe = {
        "name": raw.get("name", "").strip(),
        "source": "sankey_database",
    }

    if raw.get("source"):
        recipe["attribution"] = raw["source"].strip()

    # Parse cone
    if raw.get("cone"):
        recipe["cone"] = parse_cone(raw["cone"])

    # Parse atmosphere from firing field
    if raw.get("firing"):
        atm = parse_atmosphere(raw["firing"])
        if atm:
            recipe["atmosphere"] = atm
        recipe["firing_notes"] = raw["firing"].strip()

    # Parse ingredients
    if raw.get("ingredients"):
        recipe["ingredients"] = parse_ingredients(raw["ingredients"])

    # Parse surface
    if raw.get("surface"):
        recipe["surface"] = parse_surface(raw["surface"])

    # Other fields
    if raw.get("flaws"):
        recipe["flaws"] = raw["flaws"].strip()
    if raw.get("tester"):
        recipe["tester"] = raw["tester"].strip()
    if raw.get("notes"):
        recipe["notes"] = raw["notes"].strip()
    if raw.get("color"):
        recipe["color_description"] = raw["color"].strip()
    if raw.get("opacity"):
        recipe["opacity"] = raw["opacity"].strip()

    return recipe


def main():
    parser = argparse.ArgumentParser(description="Parse Sankey Glaze Database")
    parser.add_argument("--input", type=Path, help="Path to local Sankey text file")
    parser.add_argument("--download", action="store_true", help="Download from web")
    args = parser.parse_args()

    if args.input:
        text = args.input.read_text(encoding="utf-8")
    elif args.download:
        text = download_sankey()
    else:
        print("Provide --input PATH or --download")
        sys.exit(1)

    recipes = parse_sankey_text(text)
    print(f"Parsed {len(recipes)} recipes")

    # Save
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "recipes.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "source": "John Sankey's Glaze Database",
            "url": "https://johnsankey.ca/glazedata.html",
            "license": "Free use - no copyright on recipes",
            "recipes": recipes,
        }, f, indent=2)
    print(f"Saved to {output_path}")


if __name__ == "__main__":
    main()
