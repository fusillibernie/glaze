# Ceramic Glaze Reference Data Sources -- Research Report
**Date:** 2026-03-18
**Purpose:** Identify structured data sources for integration into the Glaze formulation tool (UMF analysis / Stull chart)

---

## Executive Summary

The single most valuable source is the **Glazy public data repository** (CC BY-NC-SA 4.0), which provides thousands of recipes with full UMF analyses in YAML/CSV format, ready for programmatic ingestion. Beyond that, the **Sankey database**, **Digitalfire materials encyclopedia**, and published **UMF limit formula tables** provide complementary structured data. Academic sources from Alfred University and the American Ceramic Society offer rigorous Stull chart validation data. Reference books are best treated as manual-extraction sources for curated "classic" recipes.

---

## 1. Reference Books -- Availability Assessment

Direct searches for these titles on Anna's Archive via web search did not return indexed results (Anna's Archive blocks search engine crawling). However, several are available on Internet Archive (archive.org) for controlled digital lending.

| Book | Internet Archive | Data Type | Extraction Difficulty |
|------|-----------------|-----------|----------------------|
| Daniel Rhodes -- *Clay and Glazes for the Potter* (1973 rev.) | **Yes** -- multiple editions, including [full text (DjVu)](https://archive.org/details/clayandclazesfor006089mbp) | Prose with embedded tables of oxide analyses, glaze formulas by cone range | Medium -- tables are in-text, not machine-readable |
| John Britt -- *Complete Guide to High-Fire Glazes* (2007) | **Yes** -- [controlled lending](https://archive.org/details/completeguidetoh0000brit) | ~200+ tested recipes with ingredients, cone, atmosphere, surface. Some UMF data | Medium -- recipes are structured but in page layout |
| John Britt -- *Complete Guide to Mid-Range Glazes* (2014) | Available via [author's site](https://johnbrittpottery.com/shop/the-complete-guide-to-mid-range/) | Same format as High-Fire | Medium |
| Linda Bloomfield -- *Colour in Glazes* (2013/2019) | Not found on IA | Systematic colorant oxide tables (8 oxides x base glazes). Author has PhD in Materials Science -- data is rigorous | Medium-High -- charts and color photos |
| Hamer & Hamer -- *Potter's Dictionary* (5th ed.) | **Yes** -- [controlled lending](https://archive.org/details/pottersdictionar0000hame) | Encyclopedia format: oxide properties, material analyses, formula tables | High -- dictionary layout, dispersed data |
| Michael Bailey -- *Glazes Cone 6* | Not confirmed on IA | Cone 6 recipes with analyses | Would need physical copy |
| Robin Hopper -- *The Ceramic Spectrum* | Not confirmed on IA | Broad survey of glaze types | Would need physical copy |

**Recommendation:** Rhodes and Britt are the highest-value book sources. The recipes in Britt's books have been partially entered into Glazy already. For systematic colorant data, Bloomfield's *Colour in Glazes* is uniquely structured but would require manual OCR/extraction.

---

## 2. Open Data Sources

### 2a. Glazy Public Data (PRIORITY 1)

| Attribute | Detail |
|-----------|--------|
| **URL** | https://github.com/derekphilipau/glazy-data |
| **License** | CC BY-NC-SA 4.0 |
| **Formats** | YAML (compressed .yaml.gz), legacy CSV |
| **Volume** | Thousands of recipes + materials (full public database) |
| **Fields** | ID, Name, Type (Material/Recipe), Subtype, Cone, Surface type, Atmosphere, Description, Ingredients (name + %), Percent Analysis (all oxides), UMF analysis, Mol% analysis, RGB color values |
| **Updates** | Periodic dumps (latest 2026) |
| **Integration** | **Trivial** -- YAML/CSV parse directly into Python/Pydantic models |

**Data lineage:** Seeded from Linda Arbuckle's GlazeChem, John Sankey's database, and Louis Katz's HyperGlaze database. Grown significantly via community contributions.

**Glazy also has a Laravel-based API** (JWT auth) at glazy.org, though the public data dump is more practical for bulk integration.

### 2b. Sankey Glaze Database (PRIORITY 2)

| Attribute | Detail |
|-----------|--------|
| **URL** | https://johnsankey.ca/glazedata.html |
| **License** | Free use -- "no copyright on recipes" |
| **Format** | Structured text with field codes (A=name, B=source, C=cone, D=firing, E=ingredients, F=surface, G=flaws, H=tester) |
| **Volume** | ~300+ recipes |
| **Quality** | Standardized testing by Alisa Clausen. Excludes lead/cadmium. Flags toxic (>10% BaO) |
| **Integration** | Easy -- regex parse the field-coded text format |

### 2c. Digitalfire Reference Library (PRIORITY 3 -- Materials)

| Attribute | Detail |
|-----------|--------|
| **URL** | https://digitalfire.com/material/list |
| **License** | Proprietary content, free to read |
| **Format** | Web pages (no API). MDT (XML) export available via Insight software |
| **Volume** | 4,000+ pages, comprehensive material oxide analyses |
| **Key value** | Individual material oxide analyses (e.g., Custer Feldspar, EPK, Nepheline Syenite) |
| **Integration** | Medium -- would need to scrape or manually extract key material analyses. MDT files are XML and parseable |

### 2d. Glaze Spectrum (SUPPLEMENTARY)

| Attribute | Detail |
|-----------|--------|
| **URL** | https://www.glazespectrum.com/ |
| **License** | Not specified (web resource) |
| **Format** | Web-only, no API or download |
| **Volume** | 243 unique glazes from 1,500+ tests |
| **Key value** | Systematic colorant testing: 8 metal oxides x 8 base glazes x 7 clays x multiple firings |
| **Integration** | Hard -- would require scraping. No bulk download |

### 2e. Ceramic Arts Network Recipes (SUPPLEMENTARY)

| Attribute | Detail |
|-----------|--------|
| **URL** | https://ceramicartsnetwork.org/ceramic-recipes |
| **Format** | Web-only, behind partial paywall |
| **Integration** | Not practical for bulk ingestion |

### 2f. HyperGlaze (LEGACY)

| Attribute | Detail |
|-----------|--------|
| **URL** | https://hyperglaze.com/ |
| **Format** | .hgz files, 300+ material analyses |
| **Status** | Legacy software (Mac OS 9/X, Win 7 era). Data already migrated into Glazy |
| **Integration** | Not recommended -- data is in Glazy already |

### 2g. Alfred University NYSCC

No public database found. The Scholes Library has 100,000+ volumes but no open digital glaze composition database. Academic papers from Alfred (see Section 3) are the accessible output.

---

## 3. Scientific / Academic Sources

### 3a. UMF & Stull Chart Research

| Paper | Source | Key Data |
|-------|--------|----------|
| Carty & Senapati -- "The Unity Molecular Formula Approach to Glaze Development" (2000) | Alfred University / American Ceramic Society ([PDF available](https://aura.alfred.edu/items/8dcdba0c-9b1e-4a6f-83eb-36fbfb8243c7)) | Defines UMF limits for simple glaze compositions. Uses Glossmeter, SEM/EDS, XRD, ICP-AES. 152-page thesis with extensive composition tables |
| "Glaze Development with Application of Unity Molecular Formula" | [ResearchGate](https://www.researchgate.net/publication/308977039) | UMF-based glaze development methodology |
| "UMF Phase Diagrams -- Guidemaps for Ceramic Glaze Development" (2019) | *Ceramics Art + Perception -- Technical*, Issue 113, pp. 130-135. [Academia.edu](https://www.academia.edu/104383295/) | Phase diagrams showing Al2O3-SiO2 regions for matte/gloss at various flux compositions. Tests BaO, CaO, boron effects |
| Stull's original research (1912) | Cone 11 data. Validated at cone 6 by multiple researchers | Al2O3 vs SiO2 grid predicting matte (<5:1 Si:Al ratio) vs gloss (>5:1). Note: considered "obsolete" in strict scientific terms but empirically useful |

### 3b. Colorant Interaction Research

| Paper | Key Data |
|-------|----------|
| "Effects of cobalt, copper, manganese and titanium oxide additions on the microstructures of zinc containing soft porcelain glazes" (2002) | [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0955221901004563) -- Microstructural analysis of colorant oxides in glazes |

### 3c. Machine Learning on Ceramic Data

| Paper | Dataset | Relevance |
|-------|---------|-----------|
| "Advanced ML models for prediction of ceramic tiles' properties during firing" (2025) | 312 ceramic samples, 1000-1300C | CatBoost model for property prediction |
| "Explainable ML classification of traditional Korean ceramics using XRF" (2026) | 624 samples with XRF composition | Random forest achieving 95.8% accuracy |
| Glazy's own ML example | Jupyter notebook in glazy-data repo | Cone prediction from composition -- directly reusable |

---

## 4. UMF Limit Formula Tables (STRUCTURED DATA -- READY TO USE)

These are the most immediately useful structured datasets. They define "safe operating windows" for glaze formulation by cone range and surface type.

### Val Cushing Limits

**Cone 5-6 Glossy:**
```
KNaO:  0.05 - 0.60    Al2O3: 0.10 - 0.30
Li2O:  0.00 - 0.50    B2O3:  0.00 - 1.00
CaO:   0.05 - 0.60    SiO2:  1.50 - 4.00
MgO:   0.00 - 0.10
ZnO:   0.00 - 0.15
BaO:   0.00 - 0.15
SrO:   0.00 - 0.15
```

**Cone 5-6 Satin:**
```
KNaO:  0.05 - 0.35    Al2O3: 0.20 - 0.40
Li2O:  0.00 - 0.15    B2O3:  0.00 - 0.50
CaO:   0.05 - 0.70    SiO2:  2.00 - 3.50
MgO:   0.00 - 0.35
ZnO:   0.00 - 0.30
BaO:   0.00 - 0.35
SrO:   0.00 - 0.35
```

**Cone 5-6 Matte:**
```
KNaO:  0.05 - 0.30    Al2O3: 0.20 - 0.50
Li2O:  0.00 - 0.10    B2O3:  0.00 - 0.50
CaO:   0.05 - 0.80    SiO2:  2.00 - 3.00
MgO:   0.00 - 0.45
ZnO:   0.00 - 0.40
BaO:   0.00 - 0.50
SrO:   0.00 - 0.50
```

**Cone 9-10 Glossy:**
```
KNaO:  0.05 - 0.50    Al2O3: 0.20 - 0.50
Li2O:  0.00 - 0.40    B2O3:  0.00 - 0.50
CaO:   0.05 - 0.80    SiO2:  2.00 - 6.00
MgO:   0.00 - 0.15
ZnO:   0.00 - 0.15
BaO:   0.00 - 0.15
SrO:   0.00 - 0.15
```

**Cone 9-10 Satin:**
```
KNaO:  0.05 - 0.40    Al2O3: 0.25 - 0.60
Li2O:  0.00 - 0.20    B2O3:  0.00 - 0.40
CaO:   0.05 - 0.80    SiO2:  2.00 - 5.00
MgO:   0.00 - 0.50
ZnO:   0.00 - 0.40
BaO:   0.00 - 0.50
SrO:   0.00 - 0.50
```

**Cone 9-10 Matte:**
```
KNaO:  0.05 - 0.30    Al2O3: 0.25 - 0.80
Li2O:  0.00 - 0.10    B2O3:  0.00 - 0.20
CaO:   0.05 - 0.90    SiO2:  2.00 - 5.00
MgO:   0.00 - 0.60
ZnO:   0.00 - 0.50
BaO:   0.00 - 0.60
SrO:   0.00 - 0.60
```

### Hesselberth & Roy Limits (Food-Safe Focus)

**Cone 5-6:**
```
KNaO:  0.01 - 0.03    Al2O3: 0.00 - 0.20
PbO:   0.20 - 0.60    B2O3:  0.15 - 0.35
CaO:   0.00 - 0.20    SiO2:  2.50 - 4.00
MgO:   0.25 - 0.40
```

**Cone 9-10:**
```
KNaO:  0.10 - 0.30    Al2O3: 0.30 - 0.60
CaO:   0.30 - 0.70    B2O3:  0.00 - 0.30
ZnO:   0.00 - 0.40    SiO2:  3.00 - 5.00
MgO:   0.00 - 0.30
```

### UK Traditional Industry Limits

| Oxide | Cone 04-02 | Cone 3-7 | Cone 8-10 |
|-------|-----------|---------|----------|
| CaO | 0.1-0.6 | 0.1-0.7 | 0.35-0.8 |
| ZnO | 0-0.20 | 0-0.25 | 0-0.3 |
| BaO | 0-0.3 | 0-0.3 | 0-0.3 |
| MgO | 0-0.3 | 0-0.3 | 0-0.4 |
| KNaO | 0-0.5 | 0.1-0.5 | 0.1-0.5 |
| B2O3 | 0.3-1.1 | 0-0.4 | 0-0.3 |
| Al2O3 | 0.1-0.4 | 0.2-0.35 | 0.3-0.55 |
| SiO2 | 1.5-3.0 | 2.5-3.5 | 3.0-5.0 |

### Green & Cooper Limits

| Oxide | Cone 04 | Cone 6 | Cone 10 |
|-------|---------|--------|---------|
| CaO | 0-0.3 | 0-0.55 | 0-0.7 |
| ZnO | 0-0.18 | 0-0.3 | 0-0.36 |
| BaO | 0-0.28 | 0-0.4 | 0-0.475 |
| MgO | 0-0.3 | 0-0.325 | 0-0.34 |
| KNaO | 0-0.525 | 0-0.375 | 0-0.3 |
| B2O3 | 0-1.0 | 0-0.35 | 0-0.225 |
| Al2O3 | 0.1-0.45 | 0.275-0.65 | 0.45-0.825 |
| SiO2 | 1.375-3.15 | 2.4-4.7 | 3.5-6.4 |

---

## 5. Raw Material Data

### USGS Mineral Resources
- **URL:** https://mrdata.usgs.gov/mrds/ (Mineral Resources Data System)
- **Data:** Geochemical data for 1.5M+ samples (1962-2023). Feldspar, kaolin, silica yearbooks as PDF
- **Integration:** PDFs require extraction. MRDS is queryable but oriented toward geology, not ceramic formulation
- **Verdict:** Low priority for glaze tool -- too raw/geological

### Supplier Technical Data Sheets
- Oxide analyses for commercial ceramic materials (Custer Feldspar, EPK, Nepheline Syenite A270, etc.) are published on Digitalfire material pages
- Suppliers like HPF Minerals publish TDS with oxide breakdowns
- **Best approach:** Use Digitalfire's material analyses as the reference -- they already normalize supplier data for ceramic use

### Key Material Oxide Analyses (from Digitalfire)
Materials like potash feldspar typically show:
- SiO2: ~67%, Al2O3: ~18%, K2O: ~12%, Na2O: ~2%, CaO: <0.3%, Fe2O3: <0.1%
- These are already in Glazy's materials database

---

## 6. Integration Priority Matrix

| Priority | Source | Data Type | Volume | Effort | Value |
|----------|--------|-----------|--------|--------|-------|
| **1** | Glazy public data (GitHub) | Recipes + materials + UMF | Thousands | Low (YAML/CSV) | **Critical** |
| **2** | UMF limit formulas (Cushing, H&R, G&C, UK) | Oxide range tables | ~30 limit sets | Trivial (already extracted above) | **High** |
| **3** | Sankey database | Tested recipes | ~300 | Low (text parse) | **High** |
| **4** | Digitalfire materials | Material oxide analyses | Hundreds | Medium (scrape/MDT) | **High** |
| **5** | Stull chart data (academic papers) | Al2O3/SiO2 boundary coordinates | Small | Medium (PDF extraction) | **High** |
| **6** | Glaze Spectrum | Colorant systematic tests | 243 | High (scrape) | **Medium** |
| **7** | Bloomfield's colorant tables | Oxide-color relationships | ~50-100 entries | High (manual/OCR) | **Medium** |
| **8** | Britt recipe books | Curated recipes | ~400 total | High (OCR from IA) | **Medium** |
| **9** | USGS mineral data | Raw mineral compositions | Large | High | **Low** |

---

## 7. Discrepancies & Bias Notes

### Triangulation Issues Found:
1. **Stull chart validity:** Digitalfire notes the chart is "112 years old and completely obsolete in terms of science." However, Glazy, academic papers, and studio potters all validate it empirically at cone 6 and cone 10. **Resolution:** Use Stull as a practical heuristic, not a scientific absolute. Flag predictions as "empirical guidance."

2. **Limit formula variation:** Cushing, Hesselberth & Roy, Green & Cooper, and UK Traditional limits disagree on ranges. For example, at cone 6:
   - Al2O3 min: Cushing says 0.10, G&C says 0.275, UK says 0.20
   - SiO2 max: Cushing says 4.0, G&C says 4.7, UK says 3.5

   **Resolution:** Present multiple limit formula overlays (as Glazy already does) rather than picking one as "correct."

3. **Digitalfire editorial bias:** Tony Hansen's articles sometimes promote Insight software and his methodology over alternatives. Cross-reference Digitalfire material analyses against Glazy and supplier TDS data.

4. **Glazy community data quality:** Community-submitted recipes vary in testing rigor. Recipes marked as "tested" or with photos are more reliable. Filter on these attributes during ingestion.

---

## 8. Concrete Next Steps

1. **Download and parse glazy-data YAML** -- this is the single highest-impact action. The YAML contains everything needed: recipes, materials, UMF analyses, cone ranges, surface types, atmosphere, and even RGB color values.

2. **Encode limit formula tables** as JSON config -- the tables extracted in Section 4 above can be directly encoded as validation boundaries in the formulator service.

3. **Parse Sankey database** -- simple regex parser for the field-coded format. Good supplementary data with quality testing notes.

4. **Extract Stull chart boundary data** from the Carty thesis (PDF at Alfred University) -- this provides the Al2O3/SiO2 coordinates that define matte/satin/gloss regions.

5. **Build a materials oxide analysis reference** from Digitalfire MDT exports or by extracting key materials from Glazy's materials data.
