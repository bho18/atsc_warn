# Alert maps

WarnBridge uses **Leaflet 1.9.4**, an open source BSD-2-Clause map engine. JavaScript,
CSS and image assets ship locally, with their license and integrity manifest under
`src/warnbridge/web/vendor/leaflet/`. No CDN, API key, account or browser location
permission is needed. The map displays the selected alert information block's
supplied coordinates; original XML and coordinate strings remain unchanged.

Pan by dragging, zoom with the controls/pinch/keyboard, and select a boundary for
its area name and shape details. **Fit alert areas** restores the view to all
supplied shapes. Polygons are green and approximate circle boundaries are dashed
amber. The map includes a metric/imperial scale. Changing languages replaces the
map with that information block's areas; geocodes alone never generate a boundary.

## Basemap choices

**Offline reference** is the default and makes no external requests. Bundled
Natural Earth vector data provides world countries, US state boundaries and selected
city labels. It is a generalized reference map without roads, parcels or detailed
coastlines. It is not a targeting/coverage determination or an alert-area source.
Alert geometry is drawn independently above these reference features.
Dedicated foreground panes keep alert boundaries above tiles and labels. A contrasting
outline and darker green/amber strokes on street tiles keep the shapes readable;
switching basemaps or completing tile loads reapplies their styling and ordering.

**Street map (online)** explicitly loads OpenStreetMap tiles from
`https://tile.openstreetmap.org/{z}/{x}/{y}.png`. Those requests reveal the viewed
map region and the browser's ordinary network metadata to the tile provider. No
alert body, identifier or receiver address is sent. The explicit choice persists
across inspector refreshes and other messages/languages in the current page;
reloading the page defaults to offline. Selecting offline stops
further tile loading. A tile failure returns to the bundled reference map while
keeping alert geometry. No tile download, prefetch, background polling or server
proxy is provided. Normal browser caching/referrer behavior is retained, and
OpenStreetMap contributor attribution is visible while that layer is selected.
The [OSMF tile policy](https://operations.osmfoundation.org/policies/tiles/) applies;
public tiles are best-effort and are not used to build the offline map.

Small antimeridian-crossing areas use equivalent longitudes to keep their display
local. Source coordinates stay intact. Web Mercator is used normally; shapes
outside its latitude range use Leaflet's geographic projection and disable the
incompatible street tiles. Geometry validity/plotting bounds remain those described
in protocol.md. Mapping does not establish schema validity, authenticity or
geographic relevance. CMAC geography still awaits a verified mapping/schema.

## Data and dependency provenance

- Leaflet 1.9.4 official npm distribution, BSD-2-Clause:
  https://registry.npmjs.org/leaflet/-/leaflet-1.9.4.tgz . The npm SHA-512 integrity
  value was checked before extracting browser assets. The bundled LICENSE retains
  copyright/disclaimer; provenance.json records source/integrity/archive and file
  hashes. No npm install or build step is needed at runtime or during setup.
- Natural Earth vector data, public domain, pinned author repository commit
  `ca96624a56bd078437bca8184e78163e5039ad19`:
  https://github.com/nvkelso/natural-earth-vector . The license was retrieved and
  inspected from that commit and is bundled under `web/maps/LICENSE.md`.
- Inputs: `ne_110m_admin_0_countries.geojson` (177 countries),
  `ne_110m_admin_1_states_provinces.geojson` (51 US states/district features), and
  `ne_50m_populated_places.geojson` (1,251 places). Data is reduced to necessary
  geometry/name/label/zoom fields; reference coordinates round to four decimals.
  This reduction never touches alert coordinates. The result has 1,479 features,
  455,379 bytes. Exact source URLs/input/output hashes are in
  `web/maps/provenance.json`.

To rebuild the bundled reference data, download each pinned URL in that manifest
into a local directory as `warnbridge-ne-countries.geojson`,
`warnbridge-ne-states.geojson`, `warnbridge-ne-places.geojson` and
`warnbridge-ne-license.md`. Compare input SHA-256 values with the manifest, then:

```sh
.venv/bin/python -m scripts.build_map_reference --source-dir /path/to/local-inputs
```

The builder reads only those local files. Normal startup never downloads datasets.
