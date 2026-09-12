# Data sources

<!-- GENERATED from pipeline/sources/registry.yaml by pipeline/manifest.py.
     Do not edit by hand: regenerate with `make attribution`. -->

Every figure in OmniGrid is traceable to an entry below. Values are tagged
**measured** (reported by a source), **derived** (computed from sources by a
named formula) or **modelled** (output of the supply-shed model).

## Model inputs

Data that feeds the map and the supply-shed model.

### Actual Generation Output Per Generation Unit (B1610)

- **Publisher** — Elexon
- **Version** — Insights Solution API
- **Licence** — [elexon-bmrs](https://www.elexon.co.uk/bsc/data/balancing-mechanism-reporting-agent/copyright-licence-bmrs-data/)
- **Source** — <https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/B1610>
- **Attribution** — Contains BMRS data © Elexon Limited copyright and database right 2026.

> Settlement-grade metered output per generating unit, half-hourly. This is measured electricity, not an estimate: it is the volume the unit is actually settled on.

### BM Unit reference data

- **Publisher** — Elexon
- **Version** — Insights Solution API
- **Licence** — [elexon-bmrs](https://www.elexon.co.uk/bsc/data/balancing-mechanism-reporting-agent/copyright-licence-bmrs-data/)
- **Source** — <https://bmrs.elexon.co.uk/api-documentation/endpoint/reference/bmunits/all>
- **Attribution** — Contains BMRS data © Elexon Limited copyright and database right 2026.

> 3,071 Balancing Mechanism Units, 1,682 with generation capacity. Carries gspGroupId, the published link from an embedded generator to the distribution region it feeds. No API key required. Worldwide royalty-free perpetual licence with a mandatory attribution string.

### GIS Boundaries for GB DNO Licence Areas

- **Publisher** — National Energy System Operator
- **Version** — 20240503
- **Licence** — [NESO-open-data](https://www.neso.energy/data-portal/neso-open-licence)
- **Source** — <https://www.neso.energy/data-portal/gis-boundaries-gb-dno-license-areas>
- **Attribution** — GIS Boundaries for GB DNO Licence Areas, National Energy System Operator, NESO Open Data Licence.

> The 14 licensed Distribution Network Operator areas, EPSG:27700. NESO publishes these as approximate: originally shared by Western Power Distribution, somewhat outdated, a good indication of geography rather than a surveyed boundary. Their Name field (_A, _B, ...) matches Elexon's gspGroupId, which is what makes the generator-to-region link published fact rather than inference.

### Global Integrated Power Tracker

- **Publisher** — Global Energy Monitor
- **Version** — August 2026 release
- **Licence** — [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/)
- **Source** — <https://globalenergymonitor.org/projects/global-integrated-power-tracker/>
- **Attribution** — Global Integrated Power Tracker, Global Energy Monitor, August 2026 release.
- **Access** — behind a name/email form; vendored into `data/raw/gem/` by hand and checksummed

> 182,400 facilities, 22,296 GW, 200 countries. Unit-level; units are clustered into plants during normalisation. Download requires a name/email form, so the file is vendored into data/raw/gem/ and checksummed.

### OpenStreetMap GB power infrastructure

- **Publisher** — OpenStreetMap contributors
- **Version** — live Overpass query
- **Licence** — [ODbL-1.0](https://opendatacommons.org/licenses/odbl/1-0/)
- **Source** — <https://wiki.openstreetmap.org/wiki/Power_networks>
- **Attribution** — © OpenStreetMap contributors, ODbL.

> Surveyed locations for GB power plants, transmission lines and substations. Queried by bounding box (49N-61.5N, 11.5W-3.5E) rather than by the UK admin area: the admin boundary is the land boundary, so an area query silently dropped every offshore wind farm beyond territorial waters, including Hornsea and Dogger Bank. The box also reaches France and Ireland, whose plants are classified out downstream. Matching an OSM plant to an Elexon BM Unit is a record link made by name, not a published identifier, and is marked as such per plant.

### Wikidata and Wikimedia Commons

- **Publisher** — Wikimedia Foundation
- **Version** — live API
- **Licence** — [CC0-1.0](https://creativecommons.org/publicdomain/zero/1.0/)
- **Source** — <https://www.wikidata.org/>
- **Attribution** — Structured data from Wikidata (CC0). Photographs from Wikimedia Commons, each under its own licence, credited to its author.

> OpenStreetMap records a wikidata id for 451 GB plants; 169 of those have a photograph (property P18) on Wikimedia Commons. Wikidata's own structured data is CC0, but each photograph is licensed by its photographer -- usually CC BY or CC BY-SA -- so the author and licence are fetched with the image and shown beside it.
