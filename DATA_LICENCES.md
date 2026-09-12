# Licensing: code and data are separate

The **code** in this repository is MIT licensed — see [LICENSE](LICENSE).

The **data** is not ours to license. Each dataset keeps its own terms, and every
one requires attribution. OmniGrid generates that attribution automatically from
`pipeline/sources/registry.yaml`, and shows it in the app under *Data sources*,
so the obligation is met wherever the map is published.

| Dataset | Licence | Attribution required |
|---|---|---|
| Global Energy Monitor — Global Integrated Power Tracker | CC BY 4.0 | yes |
| Elexon — BM Unit reference, B1610 metered generation | Elexon BMRS open licence | yes, exact string |
| NESO — GB DNO Licence Areas | NESO Open Data Licence | yes |
| OpenStreetMap — plants, lines, substations | **ODbL 1.0** | yes, share-alike |
| Wikidata (structured data) | CC0 | no |
| Wikimedia Commons photographs | per photograph, usually CC BY / CC BY-SA | yes, per author |
| Natural Earth | public domain | no |

## The one that carries a real obligation

OpenStreetMap is **ODbL**, which is share-alike: a *derived database* built from
it must be offered under ODbL too. That matters here because the GB build is
substantially OSM-derived — plant locations, transmission lines, substations.

So: the code is MIT, but if you redistribute the built data files under
`data/dist/`, treat the OSM-derived parts as ODbL and attribute
"© OpenStreetMap contributors". Photographs are licensed individually by their
photographers and are credited in the app beside each image; do not assume the
repository licence covers them.

Elexon's licence requires a specific string, which the app renders verbatim:

> Contains BMRS data © Elexon Limited copyright and database right.
