# Data sources

<!-- GENERATED from pipeline/sources/registry.yaml by pipeline/manifest.py.
     Do not edit by hand: regenerate with `make attribution`. -->

Every figure in OmniGrid is traceable to an entry below. Values are tagged
**measured** (reported by a source), **derived** (computed from sources by a
named formula) or **modelled** (output of the supply-shed model).

## Model inputs

Data that feeds the map and the supply-shed model.

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
