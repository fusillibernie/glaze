"""Food-contact safety assessment for a glaze recipe.

Replaces the old two-line check (PbO>0, BaO>0.1) with the risk factors
Digitalfire's food-safety article actually documents: glass stability
(low SiO2/Al2O3, flux saturation), specific formulation red flags (excess
talc, concentrated lithium, high boron frit at high fire), and known
oxide interactions (copper destabilizing other metals, particularly with
manganese). See data/reference/safety_guide.json for the source data and
full attribution.

This is guidance for spotting known risk patterns, not a certification -
the source article is explicit that only real leach testing confirms
whether a specific glaze is actually safe. Framed that way throughout.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..models.glaze import GlazeRecipe
from ..models.materials import MaterialType

logger = logging.getLogger(__name__)

_REFERENCE_DIR = Path(__file__).parent.parent.parent / "data" / "reference"

# A material this concentrated in Li2O is a "high lithium carbonate"-type
# source in the source article's sense, not a diffuse lithium feldspar
# (Lithium Carbonate itself is 40.4% Li2O; Spodumene, a common lithium
# feldspar, is only 7.5%).
_CONCENTRATED_LITHIUM_LI2O_THRESHOLD = 20.0

_TALC_BATCH_PCT_THRESHOLD = 5.0
_LITHIUM_BATCH_PCT_THRESHOLD = 5.0
_BORON_FRIT_BATCH_PCT_THRESHOLD = 10.0
_HIGH_FIRE_CONE_THRESHOLD = 6


def _load_safety_guide() -> dict:
    path = _REFERENCE_DIR / "safety_guide.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error("Error loading safety_guide.json: %s", e)
        return {}


@dataclass
class FoodSafetyFinding:
    key: str
    severity: str  # "info", "caution", "concern"
    message: str


@dataclass
class FoodSafetyAssessment:
    risk_level: str  # "low", "medium", "high"
    findings: list[FoodSafetyFinding] = field(default_factory=list)
    testing_recommendation: str = ""


class SafetyAssessor:
    """Assess a recipe's food-contact safety risk factors."""

    def __init__(self, materials_db, safety_guide: Optional[dict] = None):
        self.materials_db = materials_db
        self.safety_guide = safety_guide if safety_guide is not None else _load_safety_guide()

    def assess(
        self,
        recipe: GlazeRecipe,
        chemistry_issues: Optional[list[str]] = None,
        crazing_risk: Optional[str] = None,
    ) -> FoodSafetyAssessment:
        """Args:
            recipe: Recipe with ingredients, colorants and umf already set.
            chemistry_issues: analyzer.analyze_chemistry(...).issues, reused
                here rather than recomputed - a low-SiO2/low-Al2O3 issue
                flagged for surface/melt reasons is the same condition the
                source article names as the top leaching risk factor.
            crazing_risk: analyzer.analyze_thermal_expansion(...).crazing_risk,
                if a clay body fit check was run alongside this.
        """
        oxides = self.safety_guide.get("concerning_oxides", {})
        factors = self.safety_guide.get("chemistry_risk_factors", {})
        findings: list[FoodSafetyFinding] = []

        umf = recipe.umf
        if umf and umf.PbO > 0:
            findings.append(FoodSafetyFinding(
                "lead", "concern", oxides.get("PbO", {}).get("note", "Contains lead.")
            ))
        if umf and umf.BaO > 0.1:
            findings.append(FoodSafetyFinding(
                "barium", "concern", oxides.get("BaO", {}).get("note", "High barium content.")
            ))

        if chemistry_issues:
            joined = " ".join(chemistry_issues)
            if "SiO2" in joined or "Al2O3" in joined:
                findings.append(FoodSafetyFinding(
                    "low_glass_formers", "caution", factors.get("low_glass_formers", "")
                ))

        if crazing_risk in ("medium", "high"):
            findings.append(FoodSafetyFinding(
                "crazing", "caution", factors.get("crazing", "")
            ))

        talc_pct = self._batch_percentage(recipe, lambda m: m.name == "Talc")
        if talc_pct > _TALC_BATCH_PCT_THRESHOLD:
            findings.append(FoodSafetyFinding(
                "excess_talc", "caution",
                f"{talc_pct:.1f}% talc in the batch. {factors.get('excess_talc', '')}",
            ))

        lithium_pct = self._batch_percentage(
            recipe, lambda m: m.analysis.oxide_analysis.Li2O > _CONCENTRATED_LITHIUM_LI2O_THRESHOLD
        )
        if lithium_pct > _LITHIUM_BATCH_PCT_THRESHOLD:
            findings.append(FoodSafetyFinding(
                "concentrated_lithium", "caution",
                f"{lithium_pct:.1f}% of the batch is a concentrated lithium source. "
                f"{oxides.get('Li2O', {}).get('note', '')}",
            ))

        cone = self._cone_number(recipe)
        if cone is not None and cone >= _HIGH_FIRE_CONE_THRESHOLD:
            boron_frit_pct = self._batch_percentage(
                recipe,
                lambda m: m.material_type == MaterialType.FRIT and m.analysis.oxide_analysis.B2O3 > 0,
            )
            if boron_frit_pct > _BORON_FRIT_BATCH_PCT_THRESHOLD:
                findings.append(FoodSafetyFinding(
                    "high_boron_frit", "caution",
                    f"{boron_frit_pct:.1f}% boron frit at cone {cone}. "
                    f"{factors.get('high_boron_frit_high_fire', '')}",
                ))

        colorant_names = {c.material_name for c in recipe.colorants if c.percentage > 0}
        resolved_colorants = [
            (name, self.materials_db.get(name)) for name in colorant_names
        ]
        has_copper = any(
            m and m.analysis.oxide_analysis.CuO > 0 for _, m in resolved_colorants
        )
        has_manganese = any(
            m and (m.analysis.oxide_analysis.MnO > 0 or m.analysis.oxide_analysis.MnO2 > 0)
            for _, m in resolved_colorants
        )
        if has_copper and has_manganese:
            findings.append(FoodSafetyFinding(
                "copper_manganese_combination", "concern",
                oxides.get("CuO", {}).get("note", ""),
            ))
        elif has_copper and len(colorant_names) > 1:
            findings.append(FoodSafetyFinding(
                "copper_with_other_colorants", "caution",
                "Copper is known to destabilize other metals in the fired glass - "
                + oxides.get("CuO", {}).get("note", ""),
            ))

        # Always disclosed, not a computed check - the app has no way to
        # detect this from chemistry alone.
        findings.append(FoodSafetyFinding(
            "cadmium_not_tracked", "info", oxides.get("CdO", {}).get("note", "")
        ))

        concerns = sum(1 for f in findings if f.severity == "concern")
        cautions = sum(1 for f in findings if f.severity == "caution")
        if concerns > 0 or cautions >= 3:
            risk_level = "high"
        elif cautions > 0:
            risk_level = "medium"
        else:
            risk_level = "low"

        testing = self.safety_guide.get("testing_methods", {}).get("vinegar_test", "")

        return FoodSafetyAssessment(
            risk_level=risk_level,
            findings=findings,
            testing_recommendation=testing,
        )

    def _batch_percentage(self, recipe: GlazeRecipe, predicate) -> float:
        """Sum of ingredient percentages where the resolved material matches."""
        total = 0.0
        for ingredient in recipe.ingredients:
            if ingredient.percentage <= 0:
                continue
            material = self.materials_db.get(ingredient.material_name)
            if material and predicate(material):
                total += ingredient.percentage
        return total

    def _cone_number(self, recipe: GlazeRecipe) -> Optional[int]:
        try:
            return int(recipe.target_cone.value)
        except (ValueError, AttributeError):
            return None
