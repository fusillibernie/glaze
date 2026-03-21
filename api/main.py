"""FastAPI application for glaze formulation."""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from src.models.materials import Material, MaterialType
from src.models.glaze import (
    GlazeRecipe,
    GlazeIngredient,
    Colorant,
    ConeTemperature,
    AtmosphereType,
    FiringType,
    ClayBody,
    GlazeSurface,
    GlazeType,
    FiringSchedule,
)
from src.models.results import FiringResult, ResultPhoto, SurfaceQuality, GlazeDefect, ColorDescription
from src.models.umf import UMF
from src.services.materials_db import MaterialsDatabase
from src.services.formulator import GlazeFormulator, FormulationTarget
from src.services.analyzer import GlazeAnalyzer
from src.services.predictor import OutcomePredictor
from src.services.classifier import GlazeClassifier, StullRegion, GlazeCategory
from src.services.substitution_service import SubstitutionService, AvailabilityStatus
from src.integrations.glazy_client import GlazyClient
from src.services.glazy_bulk import CommunityRecipeService
from src.services.recipe_db import RecipeDatabase


limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="Glaze Formulator API",
    description="Ceramic glaze formulation and analysis tool",
    version="1.0.0",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize services
DATA_DIR = Path(__file__).parent.parent / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

materials_db = MaterialsDatabase(DATA_DIR / "materials")
formulator = GlazeFormulator(materials_db)
analyzer = GlazeAnalyzer()
predictor = OutcomePredictor()
classifier = GlazeClassifier()
substitution_service = SubstitutionService(DATA_DIR / "materials" / "substitutions.json")
glazy_client = GlazyClient(cache_dir=DATA_DIR / "glazy_cache")
community_recipes = CommunityRecipeService(DATA_DIR / "glazy_bulk" / "glazy_recipes.json")
recipe_db = RecipeDatabase(DATA_DIR)

# Mount static files for uploaded photos
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")

# UI directory
UI_DIR = Path(__file__).parent.parent / "ui"


# ============== Root Endpoint - Serve UI ==============

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main UI."""
    ui_path = UI_DIR / "index.html"
    if ui_path.exists():
        return HTMLResponse(content=ui_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Glaze Formulator</h1><p>UI not found. Check ui/index.html</p>")


# ============== Request/Response Models ==============

class IngredientInput(BaseModel):
    material_name: str
    percentage: float
    notes: Optional[str] = None


class ColorantInput(BaseModel):
    material_name: str
    percentage: float
    expected_color: Optional[str] = None


class RecipeInput(BaseModel):
    name: str
    ingredients: list[IngredientInput]
    colorants: list[ColorantInput] = []
    target_cone: str = "6"
    atmospheres: list[str] = ["oxidation"]
    glaze_type: str = "base"
    expected_surface: str = "glossy"
    notes: Optional[str] = None


class FormulationTargetInput(BaseModel):
    cone: str = "6"
    surface: str = "glossy"
    sio2_target: float = 3.5
    al2o3_target: float = 0.4
    alkali_ratio: float = 0.3
    cao_target: float = 0.4
    materials: Optional[list[str]] = None


class FiringInput(BaseModel):
    cone: str
    atmosphere: str
    firing_type: str = "electric"
    hold_time_minutes: int = 15
    cooling_rate: str = "normal"


class ResultInput(BaseModel):
    recipe_name: str
    firing_cone: str
    firing_atmosphere: str
    firing_type: str
    clay_body: str
    surface_quality: str
    color_description: str
    defects: list[str] = []
    notes: Optional[str] = None


class UMFResponse(BaseModel):
    SiO2: float
    Al2O3: float
    B2O3: float
    Na2O: float
    K2O: float
    Li2O: float
    CaO: float
    MgO: float
    BaO: float
    SrO: float
    ZnO: float
    flux_total: float
    silica_alumina_ratio: float
    alkali_ratio: float
    stull_prediction: str


class ChemistryResponse(BaseModel):
    umf: UMFResponse
    predicted_surface: str
    predicted_cone_range: tuple[int, int]
    issues: list[str]
    warnings: list[str]
    recommendations: list[str]


class PredictionResponse(BaseModel):
    predicted_surface: str
    confidence: float
    predicted_color: Optional[str]
    color_notes: Optional[str]
    defect_risks: dict[str, float]
    application_recommendations: list[str]
    firing_recommendations: list[str]


# ============== Materials Endpoints ==============

@app.get("/api/materials")
async def list_materials(
    material_type: Optional[str] = None,
    search: Optional[str] = None,
):
    """List all available materials."""
    materials = materials_db.get_all()

    if material_type:
        try:
            mt = MaterialType(material_type)
            materials = [m for m in materials if m.material_type == mt]
        except ValueError:
            pass

    if search:
        search_lower = search.lower()
        materials = [m for m in materials if search_lower in m.name.lower()]

    return [
        {
            "name": m.name,
            "type": m.material_type.value,
            "description": m.description,
            "glazy_id": m.glazy_id,
        }
        for m in materials
    ]


@app.get("/api/materials/{name}")
async def get_material(name: str):
    """Get details for a specific material."""
    material = materials_db.get(name)
    if not material:
        raise HTTPException(status_code=404, detail="Material not found")

    analysis = material.analysis.oxide_analysis
    return {
        "name": material.name,
        "type": material.material_type.value,
        "description": material.description,
        "oxide_analysis": {
            "SiO2": analysis.SiO2,
            "Al2O3": analysis.Al2O3,
            "Na2O": analysis.Na2O,
            "K2O": analysis.K2O,
            "CaO": analysis.CaO,
            "MgO": analysis.MgO,
            "Fe2O3": analysis.Fe2O3,
            "TiO2": analysis.TiO2,
            "LOI": analysis.LOI,
        },
        "glazy_id": material.glazy_id,
    }


@app.get("/api/materials/{name}/substitutes")
async def find_substitutes(name: str, limit: int = 5):
    """Find substitute materials."""
    material = materials_db.get(name)
    if not material:
        raise HTTPException(status_code=404, detail="Material not found")

    substitutes = materials_db.find_substitutes(material, limit=limit)
    return [
        {
            "name": m.name,
            "type": m.material_type.value,
            "similarity": round(sim, 2),
        }
        for m, sim in substitutes
    ]


# ============== Substitution Endpoints ==============

@app.get("/api/substitutions/status/{material_name}")
async def get_material_availability(material_name: str):
    """Get availability status and substitution info for a material."""
    sub_info = substitution_service.get_substitution_info(material_name)
    if not sub_info:
        return {
            "material": material_name,
            "status": "available",
            "reason": None,
            "substitutes": [],
        }

    return {
        "material": sub_info.material,
        "status": sub_info.status.value,
        "reason": sub_info.reason,
        "substitutes": [
            {
                "name": s.name,
                "type": s.sub_type.value,
                "ratio": s.ratio,
                "notes": s.notes,
                "components": [
                    {"material": c.material, "parts": c.parts}
                    for c in s.components
                ] if s.components else None,
                "adjustments": [
                    {"oxide": a.oxide, "change": a.change}
                    for a in s.adjustments
                ] if s.adjustments else None,
            }
            for s in sub_info.substitutes
        ],
    }


@app.get("/api/substitutions/unavailable")
async def list_unavailable_materials():
    """List all materials with availability issues."""
    unavailable = substitution_service.get_all_unavailable()
    return [
        {
            "material": name,
            "status": status.value,
            "reason": reason,
        }
        for name, status, reason in unavailable
    ]


class RecipeSubstitutionInput(BaseModel):
    recipe: dict[str, float]  # material_name -> amount
    materials_to_substitute: Optional[list[str]] = None


@app.post("/api/substitutions/calculate")
async def calculate_substitution(
    material_name: str,
    amount: float,
    substitute_index: int = 0,
):
    """Calculate amounts for substituting a material."""
    result = substitution_service.calculate_substitution(
        material_name, amount, substitute_index
    )

    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"No substitutes found for {material_name}",
        )

    return {
        "original_material": result.original_material,
        "original_amount": result.original_amount,
        "substitute_name": result.substitute_name,
        "substitute_type": result.substitute_type.value,
        "components": [
            {"material": name, "amount": amt}
            for name, amt in result.components
        ],
        "notes": result.notes,
        "adjustments": [
            {"oxide": a.oxide, "change": a.change}
            for a in result.adjustments
        ],
        "warnings": result.warnings,
    }


@app.post("/api/substitutions/recipe")
async def substitute_recipe_materials(input_data: RecipeSubstitutionInput):
    """Substitute unavailable materials in a recipe."""
    new_recipe, results = substitution_service.substitute_recipe(
        input_data.recipe,
        input_data.materials_to_substitute,
    )

    return {
        "original_recipe": input_data.recipe,
        "substituted_recipe": new_recipe,
        "substitutions": [
            {
                "original_material": r.original_material,
                "original_amount": r.original_amount,
                "substitute_name": r.substitute_name,
                "components": [
                    {"material": name, "amount": amt}
                    for name, amt in r.components
                ],
                "notes": r.notes,
                "warnings": r.warnings,
            }
            for r in results
        ],
    }


@app.post("/api/substitutions/check-recipe")
async def check_recipe_availability(recipe: dict[str, float]):
    """Check availability of all materials in a recipe."""
    issues = substitution_service.check_recipe_availability(recipe)

    return {
        "recipe_materials": list(recipe.keys()),
        "issues": [
            {
                "material": name,
                "status": status.value,
                "reason": reason,
            }
            for name, (status, reason) in issues.items()
        ],
        "all_available": len(issues) == 0,
    }


# ============== Recipe Endpoints ==============

@app.post("/api/recipes/calculate-umf")
async def calculate_umf(recipe: RecipeInput) -> UMFResponse:
    """Calculate UMF for a recipe."""
    glaze_recipe = _convert_recipe_input(recipe)
    umf = formulator.calculate_umf(glaze_recipe)

    return UMFResponse(
        SiO2=round(umf.SiO2, 4),
        Al2O3=round(umf.Al2O3, 4),
        B2O3=round(umf.B2O3, 4),
        Na2O=round(umf.Na2O, 4),
        K2O=round(umf.K2O, 4),
        Li2O=round(umf.Li2O, 4),
        CaO=round(umf.CaO, 4),
        MgO=round(umf.MgO, 4),
        BaO=round(umf.BaO, 4),
        SrO=round(umf.SrO, 4),
        ZnO=round(umf.ZnO, 4),
        flux_total=round(umf.flux_total, 4),
        silica_alumina_ratio=round(umf.silica_alumina_ratio, 2),
        alkali_ratio=round(umf.alkali_ratio, 4),
        stull_prediction=umf.stull_point.surface_prediction,
    )


@app.post("/api/recipes/analyze")
async def analyze_recipe(recipe: RecipeInput) -> ChemistryResponse:
    """Analyze glaze chemistry."""
    glaze_recipe = _convert_recipe_input(recipe)
    glaze_recipe.umf = formulator.calculate_umf(glaze_recipe)

    analysis = analyzer.analyze_chemistry(glaze_recipe)
    umf = analysis.umf

    return ChemistryResponse(
        umf=UMFResponse(
            SiO2=round(umf.SiO2, 4),
            Al2O3=round(umf.Al2O3, 4),
            B2O3=round(umf.B2O3, 4),
            Na2O=round(umf.Na2O, 4),
            K2O=round(umf.K2O, 4),
            Li2O=round(umf.Li2O, 4),
            CaO=round(umf.CaO, 4),
            MgO=round(umf.MgO, 4),
            BaO=round(umf.BaO, 4),
            SrO=round(umf.SrO, 4),
            ZnO=round(umf.ZnO, 4),
            flux_total=round(umf.flux_total, 4),
            silica_alumina_ratio=round(umf.silica_alumina_ratio, 2),
            alkali_ratio=round(umf.alkali_ratio, 4),
            stull_prediction=umf.stull_point.surface_prediction,
        ),
        predicted_surface=analysis.predicted_surface,
        predicted_cone_range=analysis.predicted_cone_range,
        issues=analysis.issues,
        warnings=analysis.warnings,
        recommendations=analysis.recommendations,
    )


@app.post("/api/recipes/predict")
async def predict_outcome(
    recipe: RecipeInput = Body(...),
    firing: FiringInput = Body(...),
    clay_body: str = Body("stoneware"),
) -> PredictionResponse:
    """Predict firing outcome."""
    glaze_recipe = _convert_recipe_input(recipe)
    glaze_recipe.umf = formulator.calculate_umf(glaze_recipe)

    firing_schedule = FiringSchedule(
        name="Custom",
        cone=ConeTemperature(firing.cone),
        atmosphere=AtmosphereType(firing.atmosphere),
        firing_type=FiringType(firing.firing_type),
        hold_time_minutes=firing.hold_time_minutes,
        cooling_rate=firing.cooling_rate,
    )

    clay = ClayBody(clay_body)

    prediction = predictor.predict_outcome(glaze_recipe, firing_schedule, clay)

    return PredictionResponse(
        predicted_surface=prediction.predicted_surface.value,
        confidence=round(prediction.confidence, 2),
        predicted_color=prediction.predicted_color_family,
        color_notes=prediction.color_notes,
        defect_risks={k: round(v, 2) for k, v in prediction.defect_risks.items()},
        application_recommendations=prediction.application_recommendations,
        firing_recommendations=prediction.firing_recommendations,
    )


@app.post("/api/recipes/formulate")
async def formulate_glaze(target: FormulationTargetInput):
    """Generate a base glaze recipe from target UMF."""
    formulation_target = FormulationTarget(
        cone=ConeTemperature(target.cone),
        surface=GlazeSurface(target.surface),
        sio2_target=target.sio2_target,
        al2o3_target=target.al2o3_target,
        alkali_ratio=target.alkali_ratio,
        cao_target=target.cao_target,
    )

    result = formulator.formulate_base_glaze(
        formulation_target,
        available_materials=target.materials,
    )

    return {
        "recipe": {
            "name": result.recipe.name,
            "ingredients": [
                {"material": i.material_name, "percentage": round(i.percentage, 2)}
                for i in result.recipe.ingredients
            ],
        },
        "achieved_umf": {
            "SiO2": round(result.achieved_umf.SiO2, 4),
            "Al2O3": round(result.achieved_umf.Al2O3, 4),
            "flux_total": round(result.achieved_umf.flux_total, 4),
        },
        "deviation_score": round(result.deviation_score, 4),
        "suggestions": result.suggestions,
    }


@app.post("/api/recipes/add-colorant")
async def add_colorant_to_recipe(
    recipe: RecipeInput,
    colorant_name: str,
    percentage: float,
    expected_color: Optional[str] = None,
):
    """Add a colorant to a recipe."""
    glaze_recipe = _convert_recipe_input(recipe)
    glaze_recipe.umf = formulator.calculate_umf(glaze_recipe)

    new_recipe = formulator.add_colorant(
        glaze_recipe,
        colorant_name,
        percentage,
        expected_color,
    )

    return {
        "name": new_recipe.name,
        "ingredients": [
            {"material": i.material_name, "percentage": round(i.percentage, 2)}
            for i in new_recipe.ingredients
        ],
        "colorants": [
            {"material": c.material_name, "percentage": c.percentage, "expected_color": c.expected_color}
            for c in new_recipe.colorants
        ],
    }


# ============== Glazy Integration Endpoints ==============

@app.get("/api/glazy/search")
@limiter.limit("30/minute")
async def search_glazy(
    request: Request,
    query: Optional[str] = None,
    cone: Optional[str] = None,
    atmosphere: Optional[str] = None,
    surface: Optional[str] = None,
    limit: int = 20,
):
    """Search Glazy.org recipes."""
    results = glazy_client.search_recipes(
        query=query,
        cone=cone,
        atmosphere=atmosphere,
        surface=surface,
        limit=limit,
    )

    return {
        "recipes": [
            {
                "glazy_id": r.glazy_id,
                "name": r.name,
                "creator": r.creator,
                "cone_range": r.cone_range,
                "atmosphere": r.atmosphere,
                "surface": r.surface,
                "image_url": r.image_url,
                "description": r.description,
            }
            for r in results
        ]
    }


@app.get("/api/glazy/recipe/{glazy_id}")
@limiter.limit("30/minute")
async def get_glazy_recipe(request: Request, glazy_id: int):
    """Fetch a recipe from Glazy.org."""
    recipe = glazy_client.get_recipe(glazy_id)
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found on Glazy")

    return {
        "name": recipe.name,
        "glazy_id": recipe.glazy_id,
        "author": recipe.author,
        "ingredients": [
            {"material": i.material_name, "percentage": i.percentage}
            for i in recipe.ingredients
        ],
        "cone": recipe.target_cone.value,
        "atmospheres": [a.value for a in recipe.suitable_atmospheres],
        "surface": recipe.expected_surface.value if recipe.expected_surface else None,
        "umf": {
            "SiO2": round(recipe.umf.SiO2, 4) if recipe.umf else None,
            "Al2O3": round(recipe.umf.Al2O3, 4) if recipe.umf else None,
        } if recipe.umf else None,
        "notes": recipe.notes,
    }


@app.get("/api/glazy/material/{glazy_id}")
@limiter.limit("30/minute")
async def get_glazy_material(request: Request, glazy_id: int):
    """Fetch a material from Glazy.org."""
    material = glazy_client.get_material(glazy_id)
    if not material:
        raise HTTPException(status_code=404, detail="Material not found on Glazy")

    analysis = material.analysis.oxide_analysis
    return {
        "name": material.name,
        "type": material.material_type.value,
        "oxide_analysis": {
            "SiO2": analysis.SiO2,
            "Al2O3": analysis.Al2O3,
            "Na2O": analysis.Na2O,
            "K2O": analysis.K2O,
            "CaO": analysis.CaO,
            "MgO": analysis.MgO,
        },
        "description": material.description,
    }


# ============== Recipe Database Endpoints ==============


@app.get("/api/recipes/search")
async def search_recipes(
    query: Optional[str] = None,
    cone: Optional[str] = None,
    atmosphere: Optional[str] = None,
    surface: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Search recipes across all sources (local, glazy-data, sankey)."""
    results = recipe_db.search(
        query=query,
        cone=cone,
        atmosphere=atmosphere,
        surface=surface,
        source=source,
        limit=limit,
        offset=offset,
    )
    total = recipe_db.count(
        cone=cone, atmosphere=atmosphere, surface=surface, source=source,
    )
    return {
        "recipes": results,
        "count": len(results),
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@app.get("/api/recipes/browse")
async def browse_recipes(
    cone: Optional[str] = None,
    atmosphere: Optional[str] = None,
    surface: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Browse recipes with pagination."""
    return recipe_db.browse(
        cone=cone,
        atmosphere=atmosphere,
        surface=surface,
        source=source,
        limit=limit,
        offset=offset,
    )


@app.get("/api/recipes/statistics")
async def recipe_statistics():
    """Get recipe database statistics."""
    return recipe_db.statistics()


@app.get("/api/recipes/sources")
async def recipe_sources():
    """Get info about loaded recipe data sources."""
    return recipe_db.get_sources()


@app.get("/api/reference/umf-limits-all")
async def get_all_umf_limits():
    """Get all UMF limit formula sets from all sources."""
    limits_path = DATA_DIR / "reference" / "umf_limits.json"
    if not limits_path.exists():
        raise HTTPException(status_code=404, detail="UMF limits file not found")
    with open(limits_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


@app.get("/api/reference/umf-limits-for-cone/{cone}")
async def get_umf_limits_for_cone(cone: str):
    """Get all UMF limit sets applicable to a specific cone."""
    limits_path = DATA_DIR / "reference" / "umf_limits.json"
    if not limits_path.exists():
        raise HTTPException(status_code=404, detail="UMF limits file not found")

    with open(limits_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    all_limits = data.get("limits", {})
    result = {}

    # Map cone to applicable limit groups
    try:
        cone_int = int(cone)
    except ValueError:
        cone_int = 6

    for range_key, limit_sets in all_limits.items():
        # Parse range from key like "cone_5_6", "cone_04_02", "cone_8_10"
        parts = range_key.replace("cone_", "").split("_")
        try:
            if len(parts) == 2:
                low = int(parts[0])
                high = int(parts[1])
                if low <= cone_int <= high:
                    result.update(limit_sets)
            elif len(parts) == 1:
                if int(parts[0]) == cone_int:
                    result.update(limit_sets)
        except ValueError:
            continue

    # Remove non-limit entries (like practical_target with no oxide ranges)
    filtered = {}
    for key, limit_set in result.items():
        if isinstance(limit_set, dict) and "SiO2" in limit_set:
            filtered[key] = limit_set

    return {"cone": cone, "limits": filtered}


# ============== Classification & Search Endpoints ==============

class ClassificationResponse(BaseModel):
    recipe_name: str
    stull_region: str
    stull_al2o3: float
    stull_sio2: float
    si_al_ratio: float
    category: str
    sub_categories: list[str]
    alkali_dominant: bool
    alkaline_earth_dominant: bool
    zinc_present: bool
    boron_present: bool
    is_iron_glaze: bool
    is_copper_glaze: bool
    is_cobalt_glaze: bool
    colorant_notes: Optional[str]
    food_safe: bool
    warnings: list[str]


@app.post("/api/classify")
async def classify_recipe(recipe: RecipeInput) -> ClassificationResponse:
    """Classify a glaze recipe based on Stull chart position and composition."""
    glaze_recipe = _convert_recipe_input(recipe)
    glaze_recipe.umf = formulator.calculate_umf(glaze_recipe)

    classification = classifier.classify(glaze_recipe)

    return ClassificationResponse(
        recipe_name=classification.recipe_name,
        stull_region=classification.stull.region.value,
        stull_al2o3=round(classification.stull.al2o3, 4),
        stull_sio2=round(classification.stull.sio2, 4),
        si_al_ratio=round(classification.stull.si_al_ratio, 2),
        category=classification.category.value,
        sub_categories=classification.sub_categories,
        alkali_dominant=classification.alkali_dominant,
        alkaline_earth_dominant=classification.alkaline_earth_dominant,
        zinc_present=classification.zinc_present,
        boron_present=classification.boron_present,
        is_iron_glaze=classification.is_iron_glaze,
        is_copper_glaze=classification.is_copper_glaze,
        is_cobalt_glaze=classification.is_cobalt_glaze,
        colorant_notes=classification.colorant_notes,
        food_safe=classification.food_safe,
        warnings=classification.warnings,
    )


@app.get("/api/search/by-region/{region}")
async def search_by_stull_region(region: str):
    """Find all glazes in a Stull chart region."""
    try:
        stull_region = StullRegion(region)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid region. Valid regions: {[r.value for r in StullRegion]}",
        )

    recipes = classifier.search_by_region(stull_region)
    return {"region": region, "count": len(recipes), "recipes": recipes}


@app.get("/api/search/by-category/{category}")
async def search_by_category(category: str):
    """Find all glazes in a category."""
    try:
        glaze_cat = GlazeCategory(category)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category. Valid categories: {[c.value for c in GlazeCategory]}",
        )

    recipes = classifier.search_by_category(glaze_cat)
    return {"category": category, "count": len(recipes), "recipes": recipes}


@app.post("/api/search/similar")
async def search_similar_glazes(
    recipe: RecipeInput,
    max_distance: float = 0.3,
    limit: int = 10,
):
    """Find glazes with similar Stull chart positions."""
    glaze_recipe = _convert_recipe_input(recipe)
    glaze_recipe.umf = formulator.calculate_umf(glaze_recipe)

    similar = classifier.search_similar(glaze_recipe, max_distance, limit)

    return {
        "reference": recipe.name,
        "similar": [
            {"name": name, "distance": round(dist, 4)}
            for name, dist in similar
        ],
    }


@app.get("/api/search/by-umf")
async def search_by_umf_range(
    sio2_min: float = 0,
    sio2_max: float = 10,
    al2o3_min: float = 0,
    al2o3_max: float = 1,
):
    """Find glazes within UMF ranges."""
    recipes = classifier.search_by_umf_range(sio2_min, sio2_max, al2o3_min, al2o3_max)

    return {
        "ranges": {
            "sio2": [sio2_min, sio2_max],
            "al2o3": [al2o3_min, al2o3_max],
        },
        "count": len(recipes),
        "recipes": recipes,
    }


@app.get("/api/search/by-flux")
async def search_by_flux_profile(
    alkali_dominant: Optional[bool] = None,
    zinc_required: bool = False,
    boron_required: bool = False,
    barium_allowed: bool = True,
):
    """Find glazes by flux composition."""
    recipes = classifier.search_by_flux_profile(
        alkali_dominant=alkali_dominant,
        zinc_required=zinc_required,
        boron_required=boron_required,
        barium_allowed=barium_allowed,
    )

    return {
        "filters": {
            "alkali_dominant": alkali_dominant,
            "zinc_required": zinc_required,
            "boron_required": boron_required,
            "barium_allowed": barium_allowed,
        },
        "count": len(recipes),
        "recipes": recipes,
    }


@app.get("/api/classify/statistics")
async def get_classification_statistics():
    """Get statistics about indexed glazes."""
    return classifier.get_statistics()


@app.get("/api/reference/stull-regions")
async def list_stull_regions():
    """List all Stull chart regions."""
    return [
        {"value": r.value, "description": _stull_region_description(r)}
        for r in StullRegion
    ]


@app.get("/api/reference/glaze-categories")
async def list_glaze_categories():
    """List all glaze categories."""
    return [{"value": c.value} for c in GlazeCategory]


def _stull_region_description(region: StullRegion) -> str:
    """Get description for a Stull region."""
    descriptions = {
        StullRegion.GLOSSY: "Typical glossy glaze region (Si:Al 8-12)",
        StullRegion.SATIN: "Satin/semi-matte region (Si:Al 6-8)",
        StullRegion.MATTE: "Matte glaze region (Si:Al < 6)",
        StullRegion.DRY_MATTE: "Dry matte, high alumina glazes",
        StullRegion.RUNNY: "May run - low alumina, high silica",
        StullRegion.UNDERFIRED: "Very low alumina - won't melt properly",
        StullRegion.STIFF: "Too high alumina - won't flow",
        StullRegion.CRYSTALLINE_ZONE: "Favorable for crystal growth",
    }
    return descriptions.get(region, "")


# ============== Results & Photo Upload Endpoints ==============

@app.post("/api/results/upload-photo")
async def upload_result_photo(
    file: UploadFile = File(...),
    result_id: Optional[str] = Form(None),
    caption: Optional[str] = Form(None),
):
    """Upload a photo of firing results."""
    # Validate file type
    allowed_types = ["image/jpeg", "image/png", "image/webp"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"File type not allowed. Allowed: {allowed_types}",
        )

    # Read and validate file size (max 10 MB)
    content = await file.read()
    max_size = 10 * 1024 * 1024
    if len(content) > max_size:
        raise HTTPException(status_code=413, detail="File too large. Maximum size is 10 MB.")

    # Derive safe extension from content type
    ext_map = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
    ext = ext_map.get(file.content_type, "jpg")
    photo_id = str(uuid.uuid4())
    filename = f"{photo_id}.{ext}"
    filepath = UPLOADS_DIR / filename

    # Save file
    with open(filepath, "wb") as f:
        f.write(content)

    return {
        "photo_id": photo_id,
        "filename": filename,
        "url": f"/uploads/{filename}",
        "caption": caption,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/results")
async def submit_result(result: ResultInput = Body(...), photo_ids: list[str] = Query(default=[])):
    """Submit a firing result."""
    result_id = str(uuid.uuid4())

    # Build photos list
    photos = []
    for pid in photo_ids:
        # Find the photo file
        for f in UPLOADS_DIR.glob(f"{pid}.*"):
            photos.append(ResultPhoto(
                photo_id=pid,
                url=f"/uploads/{f.name}",
                uploaded_at=datetime.now(timezone.utc),
            ))
            break

    # Create color description from string input
    color = ColorDescription(primary_color=result.color_description) if result.color_description else None

    firing_result = FiringResult(
        result_id=result_id,
        recipe_name=result.recipe_name,
        firing_schedule=FiringSchedule(
            name="User Firing",
            cone=ConeTemperature(result.firing_cone),
            atmosphere=AtmosphereType(result.firing_atmosphere),
            firing_type=FiringType(result.firing_type),
        ),
        clay_body=ClayBody(result.clay_body),
        surface_quality=SurfaceQuality(result.surface_quality),
        color=color,
        defects=[GlazeDefect(d) for d in result.defects],
        photos=photos,
        notes=result.notes,
        fired_at=datetime.now(timezone.utc),
    )

    # Add to predictor database
    predictor.add_result(firing_result)

    return {
        "result_id": result_id,
        "message": "Result submitted successfully",
        "photos_attached": len(photos),
    }


@app.get("/api/results")
async def list_results(
    recipe_name: Optional[str] = None,
    cone: Optional[str] = None,
    limit: int = 50,
):
    """List submitted firing results."""
    results = predictor.results

    if recipe_name:
        results = [r for r in results if recipe_name.lower() in r.recipe_name.lower()]

    if cone:
        results = [r for r in results if r.firing_schedule and r.firing_schedule.cone.value == cone]

    return [
        {
            "result_id": r.result_id,
            "recipe_name": r.recipe_name,
            "cone": r.firing_schedule.cone.value if r.firing_schedule else None,
            "atmosphere": r.firing_schedule.atmosphere.value if r.firing_schedule else None,
            "clay_body": r.clay_body.value if r.clay_body else None,
            "surface_quality": r.surface_quality.value if r.surface_quality else None,
            "color": r.color.primary_color if r.color else None,
            "photos": [{"url": p.url, "caption": p.caption} for p in r.photos],
            "fired_at": r.fired_at.isoformat() if r.fired_at else None,
        }
        for r in results[:limit]
    ]


# ============== Reference Data Endpoints ==============

@app.get("/api/reference/cones")
async def list_cones():
    """List available cone temperatures."""
    return [
        {"value": c.value, "celsius": _cone_to_celsius(c.value)}
        for c in ConeTemperature
    ]


@app.get("/api/reference/atmospheres")
async def list_atmospheres():
    """List firing atmospheres."""
    return [{"value": a.value, "description": _atmosphere_description(a)} for a in AtmosphereType]


@app.get("/api/reference/clay-bodies")
async def list_clay_bodies():
    """List clay body types."""
    return [{"value": c.value} for c in ClayBody]


@app.get("/api/reference/umf-ranges/{cone}")
async def get_umf_ranges(cone: int):
    """Get typical UMF ranges for a cone."""
    from src.models.umf import get_umf_ranges
    ranges = get_umf_ranges(cone)
    return ranges


# ============== Material Function Reference ==============

@app.get("/api/reference/material-types")
async def list_material_types():
    """List material types with usage guidelines."""
    from src.models.materials import MaterialType, MATERIAL_USAGE_GUIDELINES, MaterialFunction

    result = []
    for mat_type in MaterialType:
        guidelines = MATERIAL_USAGE_GUIDELINES.get(mat_type, {})
        result.append({
            "type": mat_type.value,
            "typical_min_percent": guidelines.get("typical_min"),
            "typical_max_percent": guidelines.get("typical_max"),
            "primary_functions": [f.value for f in guidelines.get("primary_functions", [])],
            "description": guidelines.get("description", ""),
            "notes": guidelines.get("notes", ""),
        })
    return result


@app.get("/api/reference/material-functions")
async def list_material_functions():
    """List all material functions with descriptions."""
    from src.models.materials import MaterialFunction, MATERIAL_FUNCTION_INFO

    result = []
    for func in MaterialFunction:
        info = MATERIAL_FUNCTION_INFO.get(func, {})
        result.append({
            "function": func.value,
            "description": info.get("description", ""),
            "typical_oxides": info.get("typical_oxides", []),
            "effect_on_glaze": info.get("effect_on_glaze", ""),
        })
    return result


@app.get("/api/reference/material-functions/{function}")
async def get_material_function(function: str):
    """Get detailed info about a specific material function."""
    from src.models.materials import MaterialFunction, MATERIAL_FUNCTION_INFO

    try:
        func = MaterialFunction(function)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown function: {function}")

    info = MATERIAL_FUNCTION_INFO.get(func, {})
    return {
        "function": func.value,
        "description": info.get("description", ""),
        "typical_oxides": info.get("typical_oxides", []),
        "effect_on_glaze": info.get("effect_on_glaze", ""),
    }


@app.get("/api/materials/{name}/function")
async def get_material_with_function(name: str):
    """Get a material with its function information and usage guidelines."""
    from src.models.materials import MATERIAL_USAGE_GUIDELINES

    material = materials_db.get(name)
    if not material:
        raise HTTPException(status_code=404, detail=f"Material not found: {name}")

    guidelines = MATERIAL_USAGE_GUIDELINES.get(material.material_type, {})

    return {
        "name": material.name,
        "type": material.material_type.value,
        "description": material.description,
        "analysis": material.analysis.oxide_analysis.to_dict(),
        "usage_guidelines": {
            "typical_min_percent": guidelines.get("typical_min"),
            "typical_max_percent": guidelines.get("typical_max"),
            "primary_functions": [f.value for f in guidelines.get("primary_functions", [])],
            "type_description": guidelines.get("description", ""),
            "notes": guidelines.get("notes", ""),
        },
        "substitutes": material.substitutes,
        "warnings": material.warnings,
    }


# ============== Community Recipes (Glazy Open Data) ==============

@app.get("/api/community/recipes")
async def search_community_recipes(
    query: Optional[str] = None,
    cone: Optional[str] = None,
    surface: Optional[str] = None,
    atmosphere: Optional[str] = None,
    subtype: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
):
    """Search and browse 10k+ community glaze recipes from the Glazy open database."""
    return community_recipes.search(
        query=query,
        cone=cone,
        surface=surface,
        atmosphere=atmosphere,
        subtype=subtype,
        page=page,
        page_size=page_size,
    )


@app.get("/api/community/recipes/{recipe_id}")
async def get_community_recipe(recipe_id: int):
    """Get full details for a community recipe."""
    result = community_recipes.get_by_id(recipe_id)
    if not result:
        raise HTTPException(status_code=404, detail="Community recipe not found")
    return result


@app.get("/api/community/stats")
async def community_stats():
    """Get aggregate statistics about community recipes."""
    return community_recipes.stats()


@app.get("/api/community/filters")
async def community_filters():
    """Get available filter options for community recipes."""
    return community_recipes.get_filter_options()


@app.get("/api/community/stull-neighbors")
async def community_stull_neighbors(
    sio2: float = Query(..., description="SiO2 UMF value"),
    al2o3: float = Query(..., description="Al2O3 UMF value"),
    radius: float = Query(0.5, ge=0.1, le=3.0),
    limit: int = Query(50, ge=1, le=200),
):
    """Find community recipes near a point on the Stull chart."""
    return community_recipes.stull_neighbors(sio2, al2o3, radius, limit)


@app.get("/api/community/stull-scatter")
async def community_stull_scatter(
    limit: int = Query(500, ge=50, le=2000),
):
    """Get a sample of community recipes for Stull chart overlay."""
    return community_recipes.stull_scatter(limit)


GLAZY_CDN = "https://ddms6z64wp3a6.cloudfront.net"
GLAZY_API_V2 = "https://api.glazy.org/api"
_image_cache: dict[int, Optional[dict]] = {}


@app.get("/api/community/image/{recipe_id}")
@limiter.limit("60/minute")
async def get_community_image(request: Request, recipe_id: int):
    """Get image URL for a community recipe by fetching from Glazy API."""
    if recipe_id in _image_cache:
        return _image_cache[recipe_id] or {"image_url": None}

    try:
        async_client = httpx.AsyncClient(timeout=10.0)
        resp = await async_client.get(
            f"{GLAZY_API_V2}/search",
            params={"id": recipe_id},
            headers={"Accept": "application/json"},
        )
        await async_client.aclose()
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data", [])
        if items:
            img = items[0].get("selectedImage")
            if img and img.get("filename"):
                last2 = str(recipe_id)[-2:].zfill(2)
                result = {
                    "image_url": f"{GLAZY_CDN}/uploads/recipes/{last2}/m_{img['filename']}",
                    "thumb_url": f"{GLAZY_CDN}/uploads/recipes/{last2}/s_{img['filename']}",
                    "dominant_color": img.get("dominantHexColor"),
                    "secondary_color": img.get("secondaryHexColor"),
                }
                _image_cache[recipe_id] = result
                return result

        _image_cache[recipe_id] = None
        return {"image_url": None}
    except Exception:
        return {"image_url": None}


# ============== Helper Functions ==============

def _convert_recipe_input(recipe: RecipeInput) -> GlazeRecipe:
    """Convert API input to GlazeRecipe model."""
    ingredients = [
        GlazeIngredient(
            material_name=i.material_name,
            percentage=i.percentage,
            notes=i.notes,
        )
        for i in recipe.ingredients
    ]

    colorants = [
        Colorant(
            material_name=c.material_name,
            percentage=c.percentage,
            expected_color=c.expected_color,
        )
        for c in recipe.colorants
    ]

    atmospheres = [AtmosphereType(a) for a in recipe.atmospheres]

    return GlazeRecipe(
        name=recipe.name,
        ingredients=ingredients,
        colorants=colorants,
        target_cone=ConeTemperature(recipe.target_cone),
        suitable_atmospheres=atmospheres,
        glaze_type=GlazeType(recipe.glaze_type),
        expected_surface=GlazeSurface(recipe.expected_surface),
        notes=recipe.notes,
    )


# ============== Visualization Endpoints ==============

@app.get("/api/visualization/stull-chart")
async def get_stull_chart_data():
    """Return data for rendering the Stull chart (Al2O3 vs SiO2).

    Includes Stull region boundaries and all indexed glazes.
    """
    # Stull region boundary lines (Al2O3 on x, SiO2 on y)
    # Regions defined by Si:Al ratio = SiO2 / Al2O3
    regions = [
        {
            "name": "runny",
            "label": "Runny (Si:Al > 12)",
            "color": "rgba(239,68,68,0.15)",
            "si_al_min": 12,
            "si_al_max": None,
        },
        {
            "name": "glossy",
            "label": "Glossy (Si:Al 8–12)",
            "color": "rgba(34,197,94,0.15)",
            "si_al_min": 8,
            "si_al_max": 12,
        },
        {
            "name": "satin",
            "label": "Satin (Si:Al 6–8)",
            "color": "rgba(234,179,8,0.15)",
            "si_al_min": 6,
            "si_al_max": 8,
        },
        {
            "name": "matte",
            "label": "Matte (Si:Al < 6)",
            "color": "rgba(168,85,247,0.15)",
            "si_al_min": None,
            "si_al_max": 6,
        },
    ]

    # Build glaze points from classifier index
    glazes = []
    for classification in classifier._recipe_index.values():
        if classification.stull:
            al = classification.stull.al2o3
            si = classification.stull.sio2
            if al > 0 and si > 0:
                glazes.append({
                    "name": classification.recipe_name,
                    "al2o3": round(al, 4),
                    "sio2": round(si, 4),
                    "si_al_ratio": round(classification.stull.si_al_ratio, 2),
                    "region": classification.stull.region.value,
                })

    # Load limit overlays for Stull chart
    limit_overlays = []
    limits_path = DATA_DIR / "reference" / "umf_limits.json"
    if limits_path.exists():
        try:
            with open(limits_path, "r", encoding="utf-8") as f:
                limits_data = json.load(f)
            for range_key, limit_sets in limits_data.get("limits", {}).items():
                for set_key, limit_set in limit_sets.items():
                    if isinstance(limit_set, dict) and "SiO2" in limit_set and "Al2O3" in limit_set:
                        sio2 = limit_set["SiO2"]
                        al2o3 = limit_set["Al2O3"]
                        limit_overlays.append({
                            "name": set_key,
                            "label": limit_set.get("label", set_key),
                            "cone_range": range_key,
                            "surface": limit_set.get("surface", "general"),
                            "color": limit_set.get("color", "#888"),
                            "sio2_min": sio2["min"],
                            "sio2_max": sio2["max"],
                            "al2o3_min": al2o3["min"],
                            "al2o3_max": al2o3["max"],
                        })
        except (json.JSONDecodeError, IOError):
            pass

    return {
        "regions": regions,
        "glazes": glazes,
        "limit_overlays": limit_overlays,
        "axes": {
            "x": {"label": "Al₂O₃", "min": 0.1, "max": 0.7},
            "y": {"label": "SiO₂", "min": 1.0, "max": 6.0},
        },
        "reference_lines": [
            {"si_al": 6, "label": "Matte boundary"},
            {"si_al": 8, "label": "Satin boundary"},
            {"si_al": 12, "label": "Runny boundary"},
        ],
    }


def _cone_to_celsius(cone: str) -> int:
    """Convert cone to approximate Celsius."""
    cone_temps = {
        "06": 999, "05": 1046, "04": 1060, "03": 1101,
        "02": 1120, "01": 1137, "1": 1154, "2": 1162,
        "3": 1168, "4": 1186, "5": 1196, "6": 1222,
        "7": 1240, "8": 1263, "9": 1280, "10": 1305,
        "11": 1315, "12": 1326, "13": 1346,
    }
    return cone_temps.get(cone, 1200)


def _atmosphere_description(atm: AtmosphereType) -> str:
    """Get description for atmosphere type."""
    descriptions = {
        AtmosphereType.OXIDATION: "Clean burning, typical for electric kilns",
        AtmosphereType.REDUCTION: "Oxygen-starved, typical for gas kilns",
        AtmosphereType.NEUTRAL: "Balanced atmosphere",
        AtmosphereType.HEAVY_REDUCTION: "Strong reduction, deeper color effects",
        AtmosphereType.LIGHT_REDUCTION: "Mild reduction, subtle atmosphere effects",
        AtmosphereType.WOOD: "Wood-fired with ash deposits and natural glazing",
        AtmosphereType.SALT: "Salt glazing atmosphere, orange-peel texture",
        AtmosphereType.SODA: "Soda firing atmosphere, softer than salt",
    }
    return descriptions.get(atm, "")
