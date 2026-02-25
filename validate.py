"""Validation script to check for import errors and basic functionality."""

import sys

def main():
    errors = []

    print("Validating glaze project...")
    print("-" * 50)

    # Test model imports
    print("1. Testing model imports...")
    try:
        from src.models.materials import Material, MaterialType, OxideAnalysis, OXIDE_MOLECULAR_WEIGHTS
        from src.models.umf import UMF, StullPoint, get_umf_ranges
        from src.models.glaze import (
            GlazeRecipe, GlazeIngredient, Colorant, FiringSchedule,
            ConeTemperature, AtmosphereType, FiringType, ClayBody,
            GlazeSurface, GlazeType
        )
        from src.models.results import FiringResult, ResultPhoto, SurfaceQuality, GlazeDefect, ColorDescription
        print("   [OK] All model imports successful")
    except Exception as e:
        errors.append(f"Model imports failed: {e}")
        print(f"   [ERROR] {e}")

    # Test service imports
    print("2. Testing service imports...")
    try:
        from src.services.materials_db import MaterialsDatabase
        from src.services.formulator import GlazeFormulator, FormulationTarget
        from src.services.analyzer import GlazeAnalyzer
        from src.services.predictor import OutcomePredictor
        from src.services.classifier import GlazeClassifier, StullRegion, GlazeCategory
        print("   [OK] All service imports successful")
    except Exception as e:
        errors.append(f"Service imports failed: {e}")
        print(f"   [ERROR] {e}")

    # Test integration imports
    print("3. Testing integration imports...")
    try:
        from src.integrations.glazy_client import GlazyClient
        print("   [OK] All integration imports successful")
    except Exception as e:
        errors.append(f"Integration imports failed: {e}")
        print(f"   [ERROR] {e}")

    # Test API imports
    print("4. Testing API imports...")
    try:
        from api.main import app
        print("   [OK] API imports successful")
    except Exception as e:
        errors.append(f"API imports failed: {e}")
        print(f"   [ERROR] {e}")

    # Test UMF calculation
    print("5. Testing UMF calculation...")
    try:
        from src.models.umf import UMF
        from src.models.materials import OxideAnalysis

        analysis = OxideAnalysis(
            SiO2=68.5,
            Al2O3=17.0,
            K2O=10.0,
            Na2O=3.0,
            CaO=0.3,
        )
        umf = UMF.from_oxide_analysis(analysis)
        assert umf.flux_total > 0, "Flux total should be positive"
        assert umf.SiO2 > 0, "SiO2 should be positive"
        print(f"   [OK] UMF calculation works (SiO2={umf.SiO2:.2f}, Al2O3={umf.Al2O3:.2f})")
    except Exception as e:
        errors.append(f"UMF calculation failed: {e}")
        print(f"   [ERROR] {e}")

    # Test Stull point
    print("6. Testing Stull chart...")
    try:
        from src.models.umf import StullPoint
        stull = StullPoint(al2o3=0.4, sio2=3.5)
        prediction = stull.surface_prediction
        assert prediction in ["glossy", "satin", "matte", "dry_matte", "runny", "underfired_runny", "matte_dry"]
        print(f"   [OK] Stull prediction: {prediction}")
    except Exception as e:
        errors.append(f"Stull chart failed: {e}")
        print(f"   [ERROR] {e}")

    # Test classifier
    print("7. Testing classifier...")
    try:
        from src.services.classifier import GlazeClassifier, StullRegion, GlazeCategory
        from src.models.glaze import GlazeRecipe, ConeTemperature
        from src.models.umf import UMF

        classifier = GlazeClassifier()
        recipe = GlazeRecipe(
            name="Test",
            ingredients=[],
            target_cone=ConeTemperature.CONE_6,
            umf=UMF(SiO2=3.5, Al2O3=0.4, CaO=0.6, K2O=0.3, Na2O=0.1)
        )
        classification = classifier.classify(recipe)
        assert classification.stull.region is not None
        print(f"   [OK] Classification: {classification.category.value}, region: {classification.stull.region.value}")
    except Exception as e:
        errors.append(f"Classifier failed: {e}")
        print(f"   [ERROR] {e}")

    # Test materials database loading
    print("8. Testing materials database...")
    try:
        from pathlib import Path
        from src.services.materials_db import MaterialsDatabase

        data_dir = Path(__file__).parent / "data" / "materials"
        db = MaterialsDatabase(data_dir)
        db.load()
        materials = db.get_all()
        print(f"   [OK] Loaded {len(materials)} materials")
    except Exception as e:
        errors.append(f"Materials database failed: {e}")
        print(f"   [ERROR] {e}")

    print("-" * 50)

    if errors:
        print(f"\nValidation FAILED with {len(errors)} error(s):")
        for err in errors:
            print(f"  - {err}")
        return 1
    else:
        print("\nValidation PASSED! All checks successful.")
        print("\nTo run the API server:")
        print("  uvicorn api.main:app --reload --port 8000")
        print("\nTo run tests:")
        print("  pytest tests/ -v")
        return 0


if __name__ == "__main__":
    sys.exit(main())
