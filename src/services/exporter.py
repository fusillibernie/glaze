"""CSV export of the reference data layer.

Produces flat, spreadsheet-friendly views of the materials, colorants, UMF
limit tables and substitution data so they can be checked by hand or taken
into the studio. Nested structures (limit tables, substitutes) are emitted in
long format — one row per leaf — rather than being flattened into wide rows
with sparse columns.
"""

import csv
import io
import json
import logging
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path(__file__).parent.parent.parent / "data"

# Canonical oxide column order: glass formers, then fluxes (R2O then RO), then
# colorants and minor oxides. Mirrors OXIDE_DISPLAY_ORDER in ui/index.html.
OXIDE_ORDER = [
    "SiO2", "Al2O3", "B2O3",
    "Na2O", "K2O", "Li2O",
    "CaO", "MgO", "BaO", "SrO", "ZnO", "PbO",
    "Fe2O3", "FeO", "TiO2", "MnO", "MnO2",
    "CuO", "CoO", "Cr2O3", "NiO", "V2O5",
    "ZrO2", "SnO2", "P2O5", "F",
    "LOI",
]

DATASETS = ("materials", "colorants", "umf-limits", "substitutions")


def _oxide_columns(analyses: list[dict]) -> list[str]:
    """Canonically ordered union of oxides actually present in the data."""
    present = {k for a in analyses for k, v in a.items() if isinstance(v, (int, float)) and v}
    known = [ox for ox in OXIDE_ORDER if ox in present]
    # Anything the canonical list doesn't know about still gets a column.
    return known + sorted(present - set(OXIDE_ORDER))


def _write(header: list[str], rows: list[list]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue()


def _load(data_dir: Path, *parts: str) -> dict:
    path = data_dir.joinpath(*parts)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error("Error loading %s: %s", path, e)
        return {}


def export_materials(materials_db) -> str:
    """One row per material; one column per oxide present in the set."""
    materials = materials_db.get_all()
    analyses = [m.analysis.oxide_analysis.to_dict() for m in materials]
    oxides = _oxide_columns(analyses)

    header = ["name", "type", "source", "soluble", "discontinued", "description"] + oxides
    rows = []
    for material, analysis in zip(materials, analyses):
        rows.append(
            [
                material.name,
                material.material_type.value,
                material.analysis.source or "",
                "yes" if material.soluble else "",
                "yes" if material.discontinued else "",
                material.description or "",
            ]
            + [analysis.get(ox, "") for ox in oxides]
        )
    return _write(header, rows)


def export_colorants(data_dir: Path) -> str:
    """One row per colorant/opacifier, with usage range and fired colour."""
    colorants = _load(data_dir, "materials", "colorants.json").get("colorants", [])
    analyses = [c.get("analysis", {}) for c in colorants]
    oxides = _oxide_columns(analyses)

    header = [
        "name", "type", "typical_min_pct", "typical_max_pct",
        "color_oxidation", "color_reduction", "description", "notes",
    ] + oxides
    rows = []
    for colorant in colorants:
        typical = colorant.get("typical_range") or ["", ""]
        colors = colorant.get("colors", {})
        analysis = colorant.get("analysis", {})
        rows.append(
            [
                colorant.get("name", ""),
                colorant.get("type", ""),
                typical[0] if len(typical) > 0 else "",
                typical[1] if len(typical) > 1 else "",
                colors.get("oxidation", ""),
                colors.get("reduction", ""),
                colorant.get("description", ""),
                colorant.get("notes", ""),
            ]
            + [analysis.get(ox, "") for ox in oxides]
        )
    return _write(header, rows)


def export_umf_limits(data_dir: Path) -> str:
    """Long format: one row per cone x source x oxide limit range."""
    data = _load(data_dir, "reference", "umf_limits.json")
    header = ["cone_range", "limit_source", "label", "surface", "oxide", "min", "max"]
    rows = []

    for cone_range, sources in data.get("limits", {}).items():
        for source_key, limits in sources.items():
            if not isinstance(limits, dict):
                continue
            label = limits.get("label", source_key)
            surface = limits.get("surface", "")
            for oxide, rng in limits.items():
                # Skip metadata keys; only oxide entries carry min/max.
                if not isinstance(rng, dict) or "min" not in rng:
                    continue
                rows.append([
                    cone_range.replace("cone_", "").replace("_", "-"),
                    source_key, label, surface, oxide, rng.get("min"), rng.get("max"),
                ])
    return _write(header, rows)


def export_substitutions(data_dir: Path) -> str:
    """Long format: one row per material x substitute, blends spelled out."""
    data = _load(data_dir, "materials", "substitutions.json")
    header = [
        "material", "availability_status", "reason", "alternate_names",
        "substitute", "substitute_type", "ratio", "blend_components",
        "adjustments", "notes",
    ]
    rows = []

    for entry in data.get("substitutions", []):
        material = entry.get("material", "")
        status = entry.get("status", "")
        reason = entry.get("reason", "")
        alternates = "; ".join(entry.get("alternate_names", []))

        substitutes = entry.get("substitutes", [])
        if not substitutes:
            rows.append([material, status, reason, alternates, "", "", "", "", "", ""])
            continue

        for sub in substitutes:
            components = "; ".join(
                f"{c.get('material', '')} {c.get('parts', '')}"
                for c in sub.get("components", [])
            )
            adjustments = "; ".join(
                f"{a.get('oxide', '')} {a.get('change', '')}"
                for a in sub.get("adjustments", [])
            )
            rows.append([
                material, status, reason, alternates,
                sub.get("name", ""), sub.get("type", ""), sub.get("ratio", ""),
                components, adjustments, sub.get("notes", ""),
            ])
    return _write(header, rows)


def export_dataset(dataset: str, materials_db, data_dir: Optional[Path] = None) -> str:
    """Render one named dataset as CSV. Raises ValueError on unknown names."""
    data_dir = data_dir or DEFAULT_DATA_DIR
    if dataset == "materials":
        return export_materials(materials_db)
    if dataset == "colorants":
        return export_colorants(data_dir)
    if dataset == "umf-limits":
        return export_umf_limits(data_dir)
    if dataset == "substitutions":
        return export_substitutions(data_dir)
    raise ValueError(f"Unknown dataset: {dataset}")


def export_all_zip(materials_db, data_dir: Optional[Path] = None) -> bytes:
    """Bundle every dataset into a single zip of CSVs."""
    import zipfile

    data_dir = data_dir or DEFAULT_DATA_DIR
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for dataset in DATASETS:
            zf.writestr(
                f"glaze-reference-{dataset}.csv",
                export_dataset(dataset, materials_db, data_dir),
            )
    return buf.getvalue()
