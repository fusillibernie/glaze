"""Firing results and user photo uploads."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional
from uuid import uuid4

from .glaze import (
    GlazeRecipe,
    FiringSchedule,
    ClayBody,
    GlazeSurface,
)


class SurfaceQuality(Enum):
    """Quality assessment of glaze surface."""
    EXCELLENT = "excellent"
    GOOD = "good"
    ACCEPTABLE = "acceptable"
    FLAWED = "flawed"
    FAILED = "failed"


class GlazeDefect(Enum):
    """Common glaze defects."""
    CRAWLING = "crawling"
    CRAZING = "crazing"
    SHIVERING = "shivering"
    PINHOLING = "pinholing"
    BLISTERING = "blistering"
    RUNNING = "running"
    UNDERFIRED = "underfired"
    OVERFIRED = "overfired"
    DULL_SURFACE = "dull_surface"
    COLOR_VARIATION = "color_variation"
    METALLIC_SPOTS = "metallic_spots"
    CARBON_CORING = "carbon_coring"
    BLOATING = "bloating"
    NONE = "none"


@dataclass
class ColorDescription:
    """Description of glaze color."""
    primary_color: str
    secondary_color: Optional[str] = None
    color_notes: Optional[str] = None

    # Color characteristics
    opacity: str = "opaque"  # opaque, translucent, transparent
    depth: Optional[str] = None  # shallow, medium, deep
    variation: Optional[str] = None  # solid, breaking, variegated

    # Munsell notation (optional)
    munsell_hue: Optional[str] = None
    munsell_value: Optional[int] = None
    munsell_chroma: Optional[int] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "primary_color": self.primary_color,
            "secondary_color": self.secondary_color,
            "color_notes": self.color_notes,
            "opacity": self.opacity,
            "depth": self.depth,
            "variation": self.variation,
            "munsell_hue": self.munsell_hue,
            "munsell_value": self.munsell_value,
            "munsell_chroma": self.munsell_chroma,
        }


@dataclass
class ResultPhoto:
    """A photo of a firing result."""
    photo_id: str = field(default_factory=lambda: uuid4().hex[:12])
    filename: str = ""
    file_path: Optional[str] = None
    url: Optional[str] = None

    # Photo metadata
    uploaded_at: datetime = field(default_factory=datetime.now)
    caption: Optional[str] = None

    # Image details
    width: Optional[int] = None
    height: Optional[int] = None
    file_size_bytes: Optional[int] = None

    # What's shown
    view_type: str = "general"  # general, detail, cross_section, comparison

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "photo_id": self.photo_id,
            "filename": self.filename,
            "file_path": self.file_path,
            "url": self.url,
            "uploaded_at": self.uploaded_at.isoformat(),
            "caption": self.caption,
            "width": self.width,
            "height": self.height,
            "file_size_bytes": self.file_size_bytes,
            "view_type": self.view_type,
        }


@dataclass
class FiringResult:
    """Result of firing a glaze recipe."""
    result_id: str = field(default_factory=lambda: uuid4().hex[:12])

    # What was fired
    recipe_id: Optional[str] = None
    recipe_name: str = ""
    glazy_id: Optional[int] = None

    # Firing conditions
    firing_schedule: Optional[FiringSchedule] = None
    clay_body: Optional[ClayBody] = None
    clay_body_name: Optional[str] = None

    # Application details
    application_method: str = "dip"  # dip, brush, spray, pour
    application_thickness: str = "medium"  # thin, medium, thick
    number_of_coats: int = 1
    bisque_temp: Optional[str] = None

    # Results
    surface_quality: SurfaceQuality = SurfaceQuality.GOOD
    achieved_surface: Optional[GlazeSurface] = None
    color: Optional[ColorDescription] = None
    defects: list[GlazeDefect] = field(default_factory=list)

    # Photos
    photos: list[ResultPhoto] = field(default_factory=list)

    # Assessment
    rating: Optional[int] = None  # 1-5 stars
    would_repeat: bool = True
    notes: Optional[str] = None
    lessons_learned: Optional[str] = None

    # Metadata
    fired_by: Optional[str] = None
    fired_at: datetime = field(default_factory=datetime.now)
    location: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "result_id": self.result_id,
            "recipe_id": self.recipe_id,
            "recipe_name": self.recipe_name,
            "glazy_id": self.glazy_id,
            "firing_schedule": self.firing_schedule.to_dict() if self.firing_schedule else None,
            "clay_body": self.clay_body.value if self.clay_body else None,
            "clay_body_name": self.clay_body_name,
            "application_method": self.application_method,
            "application_thickness": self.application_thickness,
            "number_of_coats": self.number_of_coats,
            "bisque_temp": self.bisque_temp,
            "surface_quality": self.surface_quality.value,
            "achieved_surface": self.achieved_surface.value if self.achieved_surface else None,
            "color": self.color.to_dict() if self.color else None,
            "defects": [d.value for d in self.defects],
            "photos": [p.to_dict() for p in self.photos],
            "rating": self.rating,
            "would_repeat": self.would_repeat,
            "notes": self.notes,
            "lessons_learned": self.lessons_learned,
            "fired_by": self.fired_by,
            "fired_at": self.fired_at.isoformat(),
            "location": self.location,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FiringResult":
        """Create from dictionary."""
        firing_schedule = None
        if data.get("firing_schedule"):
            firing_schedule = FiringSchedule.from_dict(data["firing_schedule"])

        color = None
        if data.get("color"):
            color = ColorDescription(**data["color"])

        defects = [GlazeDefect(d) for d in data.get("defects", [])]

        return cls(
            result_id=data.get("result_id", uuid4().hex[:12]),
            recipe_id=data.get("recipe_id"),
            recipe_name=data.get("recipe_name", ""),
            glazy_id=data.get("glazy_id"),
            firing_schedule=firing_schedule,
            clay_body=ClayBody(data["clay_body"]) if data.get("clay_body") else None,
            clay_body_name=data.get("clay_body_name"),
            application_method=data.get("application_method", "dip"),
            application_thickness=data.get("application_thickness", "medium"),
            number_of_coats=data.get("number_of_coats", 1),
            bisque_temp=data.get("bisque_temp"),
            surface_quality=SurfaceQuality(data.get("surface_quality", "good")),
            achieved_surface=GlazeSurface(data["achieved_surface"]) if data.get("achieved_surface") else None,
            color=color,
            defects=defects,
            rating=data.get("rating"),
            would_repeat=data.get("would_repeat", True),
            notes=data.get("notes"),
            lessons_learned=data.get("lessons_learned"),
            fired_by=data.get("fired_by"),
            location=data.get("location"),
        )
