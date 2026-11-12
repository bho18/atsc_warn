/* Leaflet is vendored under vendor/leaflet (BSD-2-Clause). All base data is local.
 * Alert text always enters Leaflet popups/labels as DOM text, never HTML strings. */
'use strict';
window.WarnBridgeMap = (() => {
  let active = null;
  let referencePromise = null;
  const polarLimit = 85.05112878;
  const element = (tag, text, className) => {
    const item = document.createElement(tag);
    if (text !== undefined) item.textContent = text;
    if (className) item.className = className;
    return item;
  };
  function clear() {
    if (!active) return;
    active.observer.disconnect();
    if (active.map) active.map.remove();
    active = null;
  }
  function reference() {
    if (!referencePromise) {
      referencePromise = fetch('/assets/maps/reference.geojson').then(response => {
        if (!response.ok) throw new Error('Offline reference map unavailable');
        return response.json();
      }).catch(error => { referencePromise = null; throw error; });
    }
    return referencePromise;
  }
  function featuresFor(areas) {
    let anchor = null;
    const features = [];
    for (const [index, area] of areas.entries()) {
      for (const original of area.geometry.features) {
        const ring = original.geometry.coordinates[0];
        if (anchor === null && ring.length) anchor = ring[0][0];
        // Equivalent longitudes keep small antimeridian areas together on screen.
        // Clone derived geometry; source coordinates and preserved evidence stay intact.
        const coordinates = ring.map(([lon, lat]) => [
          anchor + ((lon - anchor + 540) % 360) - 180, lat
        ]);
        features.push({type: 'Feature', geometry: {type: 'Polygon', coordinates: [coordinates]},
          properties: {...original.properties, number: index + 1,
            description: area.description || 'Unnamed area'}});
      }
    }
    return features;
  }
  function addReference(state, data) {
    if (active !== state) return;
    const map = state.map;
    const geography = data.features.filter(f => f.properties.layer !== 'places');
    // Render nearby wrapped worlds so reference boundaries also meet at the dateline.
    const world = Math.floor((map.getCenter().lng + 180) / 360);
    const drawWorlds = () => {
      const layer = L.geoJSON(null, {pane: 'reference', interactive: false, style: f => ({
        color: f.properties.layer === 'states' ? '#6d8187' : '#526b74',
        weight: 1, fillColor: '#263a42', fillOpacity: f.properties.layer === 'states' ? 0 : 1
      })}).addTo(map);
      for (const offset of [world - 1, world, world + 1]) {
        L.geoJSON(geography, {coordsToLatLng: ([lon, lat]) => L.latLng(lat, lon + offset * 360),
          pane: 'reference', interactive: false, style: f => ({
            color: f.properties.layer === 'states' ? '#6d8187' : '#526b74',
            weight: 1, fillColor: '#263a42', fillOpacity: f.properties.layer === 'states' ? 0 : 1
          })}).eachLayer(item => layer.addLayer(item));
      }
      return layer;
    };
    state.base = drawWorlds();
    const labels = L.layerGroup().addTo(map);
    const labelCandidates = data.features.map(feature => {
      const p = feature.properties;
      const location = p.layer === 'places'
        ? [feature.geometry.coordinates[1], feature.geometry.coordinates[0]] : p.label;
      return {...p, location};
    });
    function updateLabels() {
      labels.clearLayers();
      if (state.streets) return;
      const zoom = map.getZoom(), bounds = map.getBounds(), occupied = [];
      for (const item of labelCandidates) {
        if ((item.layer === 'countries' && zoom > 5) ||
            (item.layer === 'states' && zoom < 4) ||
            (item.layer === 'places' && zoom < Math.max(4, item.min_zoom))) continue;
        const [lat, lon] = item.location;
        const lng = lon + Math.round((map.getCenter().lng - lon) / 360) * 360;
        const point = L.latLng(lat, lng);
        if (!bounds.contains(point)) continue;
        const pixel = map.latLngToContainerPoint(point);
        if (occupied.some(other => Math.abs(other.x - pixel.x) < 95 && Math.abs(other.y - pixel.y) < 24)) continue;
        occupied.push(pixel);
        const label = element('span', item.name, `reference-label ${item.layer}`);
        const icon = L.divIcon({html: label, className: 'reference-label-icon', iconSize: [0, 0]});
        L.marker(point, {icon, pane: 'referenceLabels', interactive: false, keyboard: false}).addTo(labels);
        if (occupied.length >= 45) break;
      }
    }
    state.updateLabels = updateLabels;
    map.on('moveend zoomend', updateLabels);
    updateLabels();
    if (!state.streets) state.status.textContent = 'Offline reference map · Natural Earth';
  }
  function initialize(state, features, polar) {
    const map = L.map(state.container, {crs: polar ? L.CRS.EPSG4326 : L.CRS.EPSG3857,
      zoomAnimation: false, fadeAnimation: false, markerZoomAnimation: false,
      scrollWheelZoom: false, minZoom: 1, maxZoom: 18, attributionControl: true});
    state.map = map;
    map.createPane('reference').style.zIndex = '150';
    map.createPane('referenceLabels').style.zIndex = '350';
    map.attributionControl.setPrefix('<a href="https://leafletjs.com">Leaflet</a>');
    map.attributionControl.addAttribution('Made with <a href="https://www.naturalearthdata.com/">Natural Earth</a>');
    L.control.scale({metric: true, imperial: true}).addTo(map);
    const alerts = L.geoJSON(features, {style: feature => ({
      className: 'alert-area-shape', color: feature.properties.derived ? '#f5c678' : '#aee5bf',
      weight: 3, fillOpacity: .2, dashArray: feature.properties.derived ? '6 4' : null
    }), onEachFeature(feature, layer) {
      const p = feature.properties;
      const name = `${p.number}. ${p.description}`;
      layer.bindTooltip(element('span', name));
      const content = element('div');
      content.append(element('b', name), element('p', p.derived
        ? `Circle · ${p.radius_km} km radius · approximate boundary` : 'Polygon supplied in alert'));
      layer.bindPopup(content);
    }}).addTo(map);
    const fit = () => map.fitBounds(alerts.getBounds(), {padding: [30, 30], maxZoom: 13, animate: false});
    state.fit.onclick = fit;
    fit();
    state.container.dataset.ready = 'true';
    if (polar) {
      state.select.options[1].disabled = true;
      state.note.textContent += ' Polar coordinates use a geographic projection; street tiles are unavailable.';
    }
    state.select.onchange = () => {
      if (state.tiles) { map.removeLayer(state.tiles); state.tiles = null; }
      state.streets = state.select.value === 'streets';
      if (state.updateLabels) state.updateLabels();
      if (!state.streets) {
        state.status.textContent = state.base ? 'Offline reference map · Natural Earth' : state.referenceFailed ? 'Reference basemap unavailable · alert geometry remains visible' : 'Loading offline reference map…';
        return;
      }
      state.status.textContent = 'Loading street map…';
      const tiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
      });
      state.tiles = tiles;
      tiles.on('load', () => {
        if (active === state && state.tiles === tiles) state.status.textContent = 'Street map · OpenStreetMap';
      });
      tiles.on('tileerror', () => {
        if (active !== state || state.tiles !== tiles) return;
        map.removeLayer(tiles); state.tiles = null; state.streets = false;
        state.select.value = 'offline';
        if (state.updateLabels) state.updateLabels();
        state.status.textContent = state.base ? 'Street tiles unavailable · showing offline reference map' : 'Street tiles unavailable · alert geometry remains visible';
      });
      tiles.addTo(map);
    };
    reference().then(data => addReference(state, data)).catch(() => {
      state.referenceFailed = true;
      if (active === state && !state.streets) state.status.textContent = 'Reference basemap unavailable · alert geometry remains visible';
    });
  }
  function render(parent, areas) {
    clear();
    const features = featuresFor(areas);
    if (!features.length) {
      parent.append(element('p', 'No plottable coordinates supplied. Geocodes are retained below; no boundary is inferred.', 'muted'));
      return;
    }
    const figure = element('figure', undefined, 'area-map');
    const toolbar = element('div', undefined, 'map-toolbar');
    const label = element('label', 'Basemap');
    const select = document.createElement('select');
    select.setAttribute('aria-label', 'Map basemap');
    for (const [value, text] of [['offline', 'Offline reference'], ['streets', 'Street map (online)']]) {
      const option = element('option', text); option.value = value; select.append(option);
    }
    label.append(select);
    const fit = element('button', 'Fit alert areas'); fit.type = 'button';
    toolbar.append(label, fit);
    const container = element('div', undefined, 'alert-map');
    container.setAttribute('role', 'region'); container.setAttribute('aria-label', 'Interactive alert area map');
    const status = element('p', 'Loading offline reference map…', 'map-status');
    status.setAttribute('role', 'status');
    const note = element('figcaption', 'Green: supplied polygons. Dashed amber: approximate circles. Reference boundaries are generalized; geocodes do not imply an alert boundary. Street map loads online tiles only when selected.');
    figure.append(toolbar, container, status, note); parent.append(figure);
    const polar = features.some(f => f.geometry.coordinates[0].some(([, lat]) => Math.abs(lat) > polarLimit));
    const state = {container, select, fit, status, note, map: null, streets: false};
    state.observer = new ResizeObserver(() => {
      if (active !== state || !container.isConnected || container.clientWidth === 0 || container.clientHeight === 0) return;
      if (!state.map) initialize(state, features, polar);
      else state.map.invalidateSize({pan: false});
    });
    active = state;
    state.observer.observe(container);
  }
  return {render, clear};
})();
