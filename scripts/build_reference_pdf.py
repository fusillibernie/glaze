"""Build a printable PDF of the glaze reference data.

Renders materials (grouped by type, with oxide analyses and provenance),
colorants, UMF limit tables and substitutions into a landscape document
intended for studio use.

    py scripts/build_reference_pdf.py [output.pdf]
"""

import json
import sys
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
)

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.services.materials_db import MaterialsDatabase  # noqa: E402

DATA = Path(__file__).parent.parent / "data"

# Palette lifted from the app UI so print and screen agree.
ACCENT = colors.HexColor("#c2714f")
INK = colors.HexColor("#2b2723")
MUTED = colors.HexColor("#6b6862")
RULE = colors.HexColor("#d8d0c8")
BAND = colors.HexColor("#f7f3ef")

# Columns for the wide analysis tables. Oxides outside this set are folded
# into a trailing "Other" column so rare ones are not silently lost.
OXIDE_COLS = [
    "SiO2", "Al2O3", "B2O3", "Na2O", "K2O", "Li2O",
    "CaO", "MgO", "BaO", "SrO", "ZnO", "Fe2O3", "TiO2", "LOI",
]

TYPE_ORDER = [
    "feldspar", "silica", "clay", "calcium", "magnesium",
    "flux", "boron", "frit", "alumina", "colorant", "opacifier", "stain", "other",
]


def styles():
    s = getSampleStyleSheet()
    s.add(ParagraphStyle("DocTitle", parent=s["Title"], fontSize=26,
                         textColor=ACCENT, spaceAfter=2, leading=30))
    s.add(ParagraphStyle("Sub", parent=s["Normal"], fontSize=10,
                         textColor=MUTED, alignment=TA_CENTER, spaceAfter=18))
    s.add(ParagraphStyle("H", parent=s["Heading1"], fontSize=15,
                         textColor=ACCENT, spaceBefore=14, spaceAfter=6))
    s.add(ParagraphStyle("H2", parent=s["Heading2"], fontSize=11,
                         textColor=INK, spaceBefore=10, spaceAfter=4))
    s.add(ParagraphStyle("Body", parent=s["Normal"], fontSize=8.5,
                         textColor=INK, leading=11))
    s.add(ParagraphStyle("Note", parent=s["Normal"], fontSize=7.8,
                         textColor=MUTED, leading=10))
    s.add(ParagraphStyle("Cell", parent=s["Normal"], fontSize=7,
                         textColor=INK, leading=8.5))
    return s


def fmt(value):
    """Trim trailing zeros so columns stay scannable."""
    if not value:
        return ""
    return f"{value:g}"


def base_table_style(header_bg=ACCENT):
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), header_bg),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 7),
        ("FONTSIZE", (0, 1), (-1, -1), 7),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BAND]),
        ("GRID", (0, 0), (-1, -1), 0.25, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ])


def materials_section(story, st, db):
    story.append(Paragraph("Raw Materials", st["H"]))
    story.append(Paragraph(
        "Oxide analyses in weight percent. Blank means the oxide is absent from the "
        "published analysis, which is not the same as a measured zero. "
        "&#8224; marks a discontinued material; &#167; marks a soluble one.",
        st["Note"]))
    story.append(Spacer(1, 8))

    by_type = {}
    for m in db.get_all():
        by_type.setdefault(m.material_type.value, []).append(m)

    ordered = [t for t in TYPE_ORDER if t in by_type]
    ordered += sorted(t for t in by_type if t not in TYPE_ORDER)

    for mat_type in ordered:
        materials = sorted(by_type[mat_type], key=lambda m: m.name)
        story.append(Paragraph(mat_type.replace("_", " ").title(), st["H2"]))

        rows = [["Material"] + OXIDE_COLS + ["Other", "Source"]]
        for m in materials:
            analysis = m.analysis.oxide_analysis.to_dict()
            other = "  ".join(
                f"{k} {fmt(v)}" for k, v in analysis.items() if k not in OXIDE_COLS
            )
            marks = ("†" if m.discontinued else "") + ("§" if m.soluble else "")
            rows.append(
                [Paragraph(f"<b>{m.name}</b>{marks}", st["Cell"])]
                + [fmt(analysis.get(ox)) for ox in OXIDE_COLS]
                + [Paragraph(other, st["Cell"]),
                   Paragraph(m.analysis.source or "", st["Cell"])]
            )

        widths = ([1.55 * inch] + [0.42 * inch] * len(OXIDE_COLS)
                  + [1.15 * inch, 0.75 * inch])
        table = Table(rows, colWidths=widths, repeatRows=1)
        table.setStyle(base_table_style())
        table.setStyle(TableStyle([("ALIGN", (0, 0), (0, -1), "LEFT"),
                                   ("ALIGN", (-2, 0), (-1, -1), "LEFT")]))
        story.append(table)
        story.append(Spacer(1, 10))


def colorants_section(story, st):
    data = json.loads((DATA / "materials" / "colorants.json").read_text(encoding="utf-8"))
    story.append(PageBreak())
    story.append(Paragraph("Colorants &amp; Opacifiers", st["H"]))
    story.append(Paragraph(
        "Typical addition rates as a percentage of the dry batch, with fired colour "
        "by atmosphere. Ranges are starting points — test against your own body and schedule.",
        st["Note"]))
    story.append(Spacer(1, 8))

    rows = [["Colorant", "Type", "Typical %", "Oxidation", "Reduction", "Notes"]]
    for c in sorted(data["colorants"], key=lambda c: c["name"]):
        rng = c.get("typical_range") or []
        typical = f"{fmt(rng[0])}-{fmt(rng[1])}" if len(rng) == 2 else ""
        colours = c.get("colors", {})
        note = c.get("notes") or c.get("description") or ""
        rows.append([
            Paragraph(f"<b>{c['name']}</b>", st["Cell"]),
            c.get("type", ""),
            typical,
            Paragraph(colours.get("oxidation", ""), st["Cell"]),
            Paragraph(colours.get("reduction", ""), st["Cell"]),
            Paragraph(note, st["Cell"]),
        ])

    table = Table(rows, repeatRows=1, colWidths=[
        1.7 * inch, 0.7 * inch, 0.7 * inch, 1.7 * inch, 1.7 * inch, 3.3 * inch])
    table.setStyle(base_table_style())
    table.setStyle(TableStyle([("ALIGN", (0, 0), (1, -1), "LEFT"),
                               ("ALIGN", (3, 0), (-1, -1), "LEFT")]))
    story.append(table)


def limits_section(story, st):
    data = json.loads((DATA / "reference" / "umf_limits.json").read_text(encoding="utf-8"))
    story.append(PageBreak())
    story.append(Paragraph("UMF Limit Formulas", st["H"]))
    story.append(Paragraph(
        "Sources disagree; they are shown side by side rather than reconciled. "
        "Each has different priorities — food safety, industrial production, studio practice. "
        "Treat them as overlapping guidance, not pass/fail bounds.",
        st["Note"]))
    story.append(Spacer(1, 8))

    for cone_range, sources in data.get("limits", {}).items():
        label = cone_range.replace("cone_", "Cone ").replace("_", "-")
        story.append(Paragraph(label, st["H2"]))

        oxides = []
        for limits in sources.values():
            if not isinstance(limits, dict):
                continue
            for ox, rng in limits.items():
                if isinstance(rng, dict) and "min" in rng and ox not in oxides:
                    oxides.append(ox)

        rows = [["Source", "Surface"] + oxides]
        for key, limits in sources.items():
            if not isinstance(limits, dict) or not any(
                isinstance(v, dict) and "min" in v for v in limits.values()
            ):
                continue
            row = [Paragraph(f"<b>{limits.get('label', key)}</b>", st["Cell"]),
                   limits.get("surface", "")]
            for ox in oxides:
                rng = limits.get(ox)
                row.append(f"{fmt(rng['min'])}-{fmt(rng['max'])}"
                           if isinstance(rng, dict) and "min" in rng else "")
            rows.append(row)

        if len(rows) == 1:
            continue
        widths = [1.7 * inch, 0.6 * inch] + [0.62 * inch] * len(oxides)
        table = Table(rows, colWidths=widths, repeatRows=1)
        table.setStyle(base_table_style())
        table.setStyle(TableStyle([("ALIGN", (0, 0), (1, -1), "LEFT")]))
        story.append(table)
        story.append(Spacer(1, 10))


def substitutions_section(story, st):
    data = json.loads((DATA / "materials" / "substitutions.json").read_text(encoding="utf-8"))
    story.append(PageBreak())
    story.append(Paragraph("Substitutions", st["H"]))
    story.append(Paragraph(
        "For materials that are discontinued, scarce, or variable between batches. "
        "Ratios are by weight. A substitution changes chemistry — re-check the UMF "
        "rather than assuming equivalence.",
        st["Note"]))
    story.append(Spacer(1, 8))

    rows = [["Material", "Status", "Substitute", "Kind", "Ratio", "Blend", "Notes"]]
    for entry in sorted(data.get("substitutions", []), key=lambda e: e.get("material", "")):
        subs = entry.get("substitutes", []) or [{}]
        for i, sub in enumerate(subs):
            blend = "  ".join(
                f"{c.get('material','')} {c.get('parts','')}"
                for c in sub.get("components", []))
            rows.append([
                Paragraph(f"<b>{entry.get('material','')}</b>" if i == 0 else "", st["Cell"]),
                Paragraph(entry.get("status", "") if i == 0 else "", st["Cell"]),
                Paragraph(sub.get("name", ""), st["Cell"]),
                sub.get("type", ""),
                fmt(sub.get("ratio")),
                Paragraph(blend, st["Cell"]),
                Paragraph(sub.get("notes", ""), st["Cell"]),
            ])

    table = Table(rows, repeatRows=1, colWidths=[
        1.3 * inch, 0.6 * inch, 1.5 * inch, 0.55 * inch,
        0.45 * inch, 1.6 * inch, 3.7 * inch])
    table.setStyle(base_table_style())
    table.setStyle(TableStyle([("ALIGN", (0, 0), (3, -1), "LEFT"),
                               ("ALIGN", (5, 0), (-1, -1), "LEFT")]))
    story.append(table)


def provenance_section(story, st, db):
    story.append(PageBreak())
    story.append(Paragraph("Provenance &amp; Known Gaps", st["H"]))

    sourced = [m for m in db.get_all() if m.analysis.source]
    discontinued = [m for m in db.get_all() if m.discontinued]

    story.append(Paragraph(
        f"This reference covers <b>{len(db.get_all())}</b> materials. "
        f"<b>{len(sourced)}</b> carry an explicit analysis source; the remainder are "
        f"long-standing entries whose origin was not recorded and should be treated as "
        f"approximate. <b>{len(discontinued)}</b> are marked discontinued.",
        st["Body"]))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Attributed analyses", st["H2"]))
    rows = [["Material", "Source"]]
    for m in sorted(sourced, key=lambda m: m.name):
        rows.append([Paragraph(m.name, st["Cell"]),
                     Paragraph(m.analysis.source, st["Cell"])])
    table = Table(rows, repeatRows=1, colWidths=[2.6 * inch, 3.0 * inch])
    table.setStyle(base_table_style())
    table.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "LEFT")]))
    story.append(table)
    story.append(Spacer(1, 12))

    story.append(Paragraph("Discontinued materials", st["H2"]))
    for m in sorted(discontinued, key=lambda m: m.name):
        story.append(Paragraph(f"<b>{m.name}</b> — {m.description or ''}", st["Note"]))
        story.append(Spacer(1, 3))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Not in this reference", st["H2"]))
    story.append(Paragraph(
        "Referenced by recipes or substitution entries but absent, because no published "
        "analysis was available. Recipes using these will calculate from the remaining "
        "ingredients and flag the omission rather than silently absorbing it: "
        "<b>Tennessee Ball Clay</b>, <b>XX Saggar Ball Clay</b>, <b>Sheffield Slip</b>, "
        "<b>Fusion Frit F-69</b>, <b>Fusion Frit F-75</b>, and species-specific wood ashes "
        "(<b>oak</b>, <b>apple</b>, <b>pine</b>) whose chemistry differs enough from the "
        "mixed-hardwood entry that substituting it would mislead.",
        st["Note"]))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Caveats", st["H2"]))
    for caveat in [
        "Natural materials (Gerstley Borate, Alberta Slip, Cornwall Stone, wood ash, "
        "volcanic ash, colemanite) vary between batches and deposits. Published analyses "
        "are representative, not guaranteed.",
        "Loss on ignition is listed for reference and is excluded from UMF calculation.",
        "Cornwall Stone's analysis omits fluorine; totals will not reach 100%.",
        "Food safety cannot be inferred from chemistry alone. Barium, lithium, manganese, "
        "chrome, nickel and copper all carry leaching considerations beyond what a UMF shows.",
    ]:
        story.append(Paragraph(f"&#183; {caveat}", st["Note"]))
        story.append(Spacer(1, 3))


def decorate(canvas, doc):
    canvas.saveState()
    width, height = landscape(letter)
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.5)
    canvas.line(0.5 * inch, 0.55 * inch, width - 0.5 * inch, 0.55 * inch)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(0.5 * inch, 0.38 * inch, "Glaze — Reference Data")
    canvas.drawRightString(width - 0.5 * inch, 0.38 * inch, f"Page {doc.page}")
    canvas.restoreState()


def build(out_path: Path):
    db = MaterialsDatabase()
    db.load()
    st = styles()

    doc = SimpleDocTemplate(
        str(out_path), pagesize=landscape(letter),
        leftMargin=0.5 * inch, rightMargin=0.5 * inch,
        topMargin=0.55 * inch, bottomMargin=0.7 * inch,
        title="Glaze Reference Data", author="Glaze",
    )

    story = [
        Paragraph("Glaze Reference Data", st["DocTitle"]),
        Paragraph(
            f"Materials, colorants, UMF limits and substitutions &#183; "
            f"generated {date.today().isoformat()}",
            st["Sub"]),
    ]
    materials_section(story, st, db)
    colorants_section(story, st)
    limits_section(story, st)
    substitutions_section(story, st)
    provenance_section(story, st, db)

    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return out_path


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("glaze-reference.pdf")
    build(target)
    print(f"wrote {target} ({target.stat().st_size / 1024:.0f} KB)")
