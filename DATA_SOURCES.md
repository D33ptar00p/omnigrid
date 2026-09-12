# Data sources

<!-- GENERATED from pipeline/sources/registry.yaml by pipeline/manifest.py.
     Do not edit by hand: regenerate with `make attribution`. -->

Every figure in OmniGrid is traceable to an entry below. Values are tagged
**measured** (reported by a source), **derived** (computed from sources by a
named formula) or **modelled** (output of the supply-shed model).

## Model inputs

Data that feeds the map and the supply-shed model.

### Access to electricity (% of population)

- **Publisher** — World Bank
- **Version** — indicator EG.ELC.ACCS.ZS
- **Licence** — [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/)
- **Source** — <https://data.worldbank.org/indicator/EG.ELC.ACCS.ZS>
- **Attribution** — World Bank, Access to electricity (% of population), CC BY 4.0.

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

### Derived map of global electricity transmission and distribution lines

- **Publisher** — World Bank / ESMAP
- **Version** — Zenodo record 3628142
- **Licence** — [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/)
- **Source** — <https://energydata.info/dataset/derived-map-of-global-electricity-transmission-and-distribution-lines>
- **Attribution** — gridfinder, World Bank / ESMAP, CC BY 4.0.

> 187 countries, ~70% accurate at 1 km. Feeds BOTH the cost matrix and the demand mask, so its errors compound — always blended against worldbank_electrification.

### GIS Boundaries for GB DNO Licence Areas

- **Publisher** — National Energy System Operator
- **Version** — 20240503
- **Licence** — [NESO-open-data](https://www.neso.energy/data-portal/neso-open-licence)
- **Source** — <https://www.neso.energy/data-portal/gis-boundaries-gb-dno-license-areas>
- **Attribution** — GIS Boundaries for GB DNO Licence Areas, National Energy System Operator, NESO Open Data Licence.

> The 14 licensed Distribution Network Operator areas, EPSG:27700. NESO publishes these as approximate: originally shared by Western Power Distribution, somewhat outdated, a good indication of geography rather than a surveyed boundary. Their Name field (_A, _B, ...) matches Elexon's gspGroupId, which is what makes the generator-to-region link published fact rather than inference.

### Global Coal Mine Tracker

- **Publisher** — Global Energy Monitor
- **Version** — 2026 release
- **Licence** — [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/)
- **Source** — <https://globalenergymonitor.org/projects/global-coal-mine-tracker/>
- **Attribution** — Global Coal Mine Tracker, Global Energy Monitor, 2026 release.
- **Access** — behind a name/email form; vendored into `data/raw/gem/` by hand and checksummed

### Global Human Settlement Layer population grid

- **Publisher** — European Commission Joint Research Centre
- **Version** — R2023A
- **Licence** — [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/)
- **Source** — <https://human-settlement.emergency.copernicus.eu/ghs_pop.php>
- **Attribution** — GHSL Global Human Settlement Layer, European Commission JRC.

> Fallback population source if kontur_pop's licence cannot be resolved cleanly.

### Global Integrated Power Tracker

- **Publisher** — Global Energy Monitor
- **Version** — August 2026 release
- **Licence** — [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/)
- **Source** — <https://globalenergymonitor.org/projects/global-integrated-power-tracker/>
- **Attribution** — Global Integrated Power Tracker, Global Energy Monitor, August 2026 release.
- **Access** — behind a name/email form; vendored into `data/raw/gem/` by hand and checksummed

> 182,400 facilities, 22,296 GW, 200 countries. Unit-level; units are clustered into plants during normalisation. Download requires a name/email form, so the file is vendored into data/raw/gem/ and checksummed.

### Global Oil and Gas Extraction Tracker

- **Publisher** — Global Energy Monitor
- **Version** — March 2026 release
- **Licence** — [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/)
- **Source** — <https://globalenergymonitor.org/projects/global-oil-gas-extraction-tracker/>
- **Attribution** — Global Oil and Gas Extraction Tracker, Global Energy Monitor, March 2026 release.
- **Access** — behind a name/email form; vendored into `data/raw/gem/` by hand and checksummed

### Global Power Plant Database

- **Publisher** — World Resources Institute
- **Version** — 1.3.0
- **Licence** — [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/)
- **Source** — <https://datasets.wri.org/datasets/global-power-plant-database>
- **Attribution** — Global Power Plant Database v1.3.0, World Resources Institute.

> Unmaintained since 2021. Used ONLY as a cross-check on modelled generation and as a degraded fallback when GEM files are not vendored. Never primary.

### Kontur Population

- **Publisher** — Kontur
- **Version** — 3km H3 global
- **Licence** — [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/)
- **Source** — <https://data.humdata.org/dataset/kontur-population-dataset-3km>
- **Attribution** — Kontur Population dataset, CC BY 4.0. Derived in part from OpenStreetMap (© OpenStreetMap contributors, ODbL) and Microsoft Buildings (ODbL).

> LICENCE RESOLVED 2026-09-12. Both Kontur and the HDX package metadata state CC BY (HDX license_id "cc-by"); the ODbL references describe Kontur's upstream inputs, not the distributed product. We attribute the upstream ODbL sources as well, which satisfies either reading at no cost. Fallback remains ghsl_pop if this is ever contested.

### Natural Earth admin boundaries

- **Publisher** — Natural Earth
- **Version** — 5.1.1 (50m cultural)
- **Licence** — [public-domain](https://www.naturalearthdata.com/about/terms-of-use/)
- **Source** — <https://www.naturalearthdata.com/>
- **Attribution** — Made with Natural Earth.

### OpenStreetMap GB power infrastructure

- **Publisher** — OpenStreetMap contributors
- **Version** — live Overpass query
- **Licence** — [ODbL-1.0](https://opendatacommons.org/licenses/odbl/1-0/)
- **Source** — <https://wiki.openstreetmap.org/wiki/Power_networks>
- **Attribution** — © OpenStreetMap contributors, ODbL.

> Surveyed locations for GB power plants, transmission lines and substations. Matching an OSM plant to an Elexon BM Unit is a record link made by name, not a published identifier, and is marked as such per plant.

### OpenStreetMap power infrastructure

- **Publisher** — OpenStreetMap contributors
- **Version** — planet, build date recorded at fetch
- **Licence** — [ODbL-1.0](https://opendatacommons.org/licenses/odbl/1-0/)
- **Source** — <https://www.openstreetmap.org/>
- **Attribution** — © OpenStreetMap contributors, ODbL.

> power=plant, power=generator, power=line, power=substation via Overpass/Geofabrik.

### Synchronous grid region table

- **Publisher** — OmniGrid
- **Version** — 1
- **Licence** — [CC0-1.0](https://creativecommons.org/publicdomain/zero/1.0/)
- **Source** — <https://github.com/omnigrid/omnigrid>
- **Attribution** — OmniGrid synchronous grid region table, CC0.

> Authored. No canonical open dataset exists. ~40 major synchronous areas. Each entry carries its own source citation. This is where the model silently breaks if curation is wrong — China's six regional grids, Japan's 50/60 Hz split, Russia's UPS zones, Brazil's isolated systems, Australia NEM/SWIS/NT.

### Yearly Electricity Data

- **Publisher** — Ember
- **Version** — Global Electricity Review yearly release, 2000-2022
- **Licence** — [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/)
- **Source** — <https://ember-energy.org/data/yearly-electricity-data/>
- **Attribution** — Yearly Electricity Data, Ember, CC BY 4.0.

> 215 geographies. The calibration target for capacity factors — the single biggest accuracy lever in the model.

## Modelled outputs

Produced by OmniGrid. Estimates, never measurements.

### OmniGrid supply-shed model

- **Publisher** — OmniGrid
- **Version** — 1
- **Licence** — [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/)
- **Source** — <https://github.com/omnigrid/omnigrid>
- **Attribution** — OmniGrid modelled supply sheds, CC BY 4.0.

> Entropy-regularised optimal transport (doubly-constrained gravity model), solved by unbalanced Sinkhorn per synchronous region. Every value citing this source is an estimate, never a measurement. See the methodology page.

## Validation sources

Deliberately held out of the model so they can test it. Never inputs.

### ENTSO-E Transparency Platform

- **Publisher** — ENTSO-E
- **Version** — current
- **Licence** — [entsoe-terms](https://transparency.entsoe.eu/content/static_content/Static%20content/terms%20and%20conditions/terms%20and%20conditions.html)
- **Source** — <https://transparency.entsoe.eu/>
- **Attribution** — ENTSO-E Transparency Platform.

> [!WARNING]
> NOT A STANDARD OPEN LICENCE. The ENTSO-E Transparency Platform has its own terms of use: free to reuse with attribution, but requiring registration and not a CC/ODbL grant. Confirm those terms permit redistribution of derived validation figures before shipping anything that depends on it. eGRID (US public domain) carries the validation on its own in the meantime.

### Electric Retail Service Territories

- **Publisher** — HIFLD / US Department of Homeland Security
- **Version** — archived 2025-08-26
- **Licence** — [public-domain](https://www.usa.gov/government-works)
- **Source** — <https://catalog.data.gov/dataset/electric-retail-service-territories>
- **Attribution** — Electric Retail Service Territories, HIFLD.

> Real regulated US/CA polygons. Sanity check on shed extent only — never an input. HIFLD Open was deactivated 2025-08-26; mirrored via Data Rescue Project.

### eGRID

- **Publisher** — US Environmental Protection Agency
- **Version** — 2024
- **Licence** — [public-domain](https://www.epa.gov/)
- **Source** — <https://www.epa.gov/egrid>
- **Attribution** — eGRID, US Environmental Protection Agency.

> Primary lambda fitting target. Never an input to the allocation.

## Basemap

Cartographic only.

### Protomaps basemap

- **Publisher** — Protomaps
- **Version** — daily planet build
- **Licence** — [ODbL-1.0](https://opendatacommons.org/licenses/odbl/1-0/)
- **Source** — <https://protomaps.com/>
- **Attribution** — © OpenStreetMap contributors, ODbL. Basemap style © Protomaps (CC0).
