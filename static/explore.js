import { initI18n, t, getLang } from '/i18n.js';
import { initAuth } from '/auth.js';

// Nutzerwunsch (2026-08-23): "Explore"-Modus - Schlagwort-/Autor:innen-
// Netzwerk als organischer, animierter D3-Force-Graph (SVG statt Canvas/
// WebGL, siehe Kommentar in style.css - bei der Datenmenge dieser App
// überwiegt der Vorteil, dass echte DOM-Elemente automatisch am
// bestehenden CSS-Theming/Dark-Mode teilnehmen). Klick auf einen Knoten
// springt in die bestehende gefilterte Quellenliste (import.html), exakt
// wie ein Autor:innen-Link in einem Zitat der Konversationsansicht schon
// heute funktioniert - keine eigene Bearbeitungsoberfläche hier. Lädt bei
// jedem Seitenaufruf frisch (kein Caching), damit eine Rückkehr aus dem
// Bearbeiten-Modus sofort den aktuellen Stand zeigt.

await initI18n();
await initAuth();

const statusEl = document.getElementById('explore-status');
const wrapEl = document.getElementById('explore-graph-wrap');
const searchInput = document.getElementById('explore-search');
const svg = d3.select('#explore-graph');

const CLUSTER_COLOR_COUNT = 10;
const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

// Nutzerfeedback (2026-08-23): das Netzwerk blieb beim Umschalten der
// Sprache deutsch, weil loadGraph() bis dahin nur einmal beim Laden der
// Seite lief - siehe i18n:changed-Listener weiter unten. Ein erneuter
// renderGraph()-Aufruf muss dafür die alte SVG-Zeichnung/Simulation/den
// alten Such-Handler zuerst vollständig entfernen, sonst würde sich ein
// zweites, unabhängig weiterlaufendes Netzwerk übereinanderlegen.
let currentSimulation = null;
let currentSearchHandler = null;

function nodeUrl(node) {
  return node.type === 'author'
    ? `/import.html?author=${encodeURIComponent(node.label)}`
    : `/import.html?term=${encodeURIComponent(node.label)}`;
}

// Radius nach Gewicht (Quellen-Anzahl) skaliert, gedeckelt, damit ein sehr
// häufiges Schlagwort/eine sehr produktive Autorin/ein sehr produktiver
// Autor die Simulation nicht dominiert.
function radiusFor(d) {
  const base = d.type === 'author' ? 16 : 6;
  const perWeight = d.type === 'author' ? 0.5 : 0.8;
  return base + Math.min(d.weight, 25) * perWeight;
}

function normalizeSearch(value) {
  return (value || '').trim().toLowerCase();
}

// Nutzerwunsch (2026-08-23): Klick auf einen Knoten öffnet NICHT mehr
// direkt die Quellenliste, sondern hebt ihn samt seiner direkt verbundenen
// Knoten/Kanten hervor (Rest gedimmt) - erneuter Klick auf denselben
// Knoten zeigt wieder das gesamte Netzwerk. source/target akzeptieren
// sowohl rohe IDs als auch von D3s forceLink bereits aufgelöste
// Knoten-Objekte, damit sich die Funktion isoliert testen lässt.
function neighborIds(nodeId, edges) {
  const ids = new Set([nodeId]);
  edges.forEach((e) => {
    const sourceId = typeof e.source === 'object' ? e.source.id : e.source;
    const targetId = typeof e.target === 'object' ? e.target.id : e.target;
    if (sourceId === nodeId) ids.add(targetId);
    if (targetId === nodeId) ids.add(sourceId);
  });
  return ids;
}

function drag(simulation) {
  function started(event, d) {
    // Nutzerfeedback (2026-08-23): 0.3 hielt bei ~300 Knoten die komplette
    // Simulation sehr "heiß" und ließ das gesamte Netzwerk sichtbar
    // zittern, wenn nur EIN Knoten gezogen wird - 0.1 reicht, damit
    // Nachbarn sanft nachrücken, ohne das ganze Netzwerk aufzuschaukeln.
    if (!event.active) simulation.alphaTarget(0.1).restart();
    d.fx = d.x;
    d.fy = d.y;
  }
  function dragged(event, d) {
    d.fx = event.x;
    d.fy = event.y;
  }
  function ended(event, d) {
    if (!event.active) simulation.alphaTarget(0);
    d.fx = null;
    d.fy = null;
  }
  return d3.drag().on('start', started).on('drag', dragged).on('end', ended);
}

function renderGraph(data) {
  const { nodes, edges } = data;
  const width = wrapEl.clientWidth;
  const height = wrapEl.clientHeight;

  currentSimulation?.stop();
  if (currentSearchHandler) {
    searchInput.removeEventListener('input', currentSearchHandler);
    currentSearchHandler = null;
  }
  svg.selectAll('*').remove();

  svg.attr('viewBox', [0, 0, width, height]).attr('width', '100%').attr('height', '100%');
  const container = svg.append('g');
  const zoomBehavior = d3
    .zoom()
    .scaleExtent([0.2, 4])
    .on('zoom', (event) => container.attr('transform', event.transform));
  svg.call(zoomBehavior);

  // Nutzerwunsch (2026-08-23): bei voller Ansicht (Skalierung 1) wirkt das
  // Netzwerk mit ~300 Knoten erschlagend dicht - startet stattdessen näher
  // herangezoomt, mittig zentriert, ganz normal mit dem Mausrad weiter
  // heraus-/hineinzoombar.
  const INITIAL_ZOOM_SCALE = 1.8;
  svg.call(
    zoomBehavior.transform,
    d3.zoomIdentity.translate(width / 2, height / 2).scale(INITIAL_ZOOM_SCALE).translate(-width / 2, -height / 2),
  );

  const simulation = d3
    .forceSimulation(nodes)
    .force(
      'link',
      d3
        .forceLink(edges)
        .id((d) => d.id)
        // Nutzerfeedback (2026-08-23): größerer Abstand, damit sich die
        // Beschriftungen (die unterhalb jedes Knotens sitzen und dabei
        // über dessen reinen Kreis-Radius hinausragen) deutlich seltener
        // überlappen - die Kollisionserkennung unten kennt nur die Kreise,
        // nicht die Textbreite, daher zusätzlich großzügiger Puffer.
        .distance(70)
        .strength(0.15),
    )
    .force('charge', d3.forceManyBody().strength(-220))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force(
      'collide',
      d3.forceCollide().radius((d) => radiusFor(d) + 34),
    )
    // Nutzerfeedback (2026-08-23): bei ~300 Knoten/~1700 Kanten schaukelte
    // sich die Simulation beim Ziehen eines einzelnen Knotens sichtbar im
    // GESAMTEN Netzwerk auf statt sich schnell zu beruhigen - mehr Reibung
    // (velocityDecay, Standard 0.4) dämpft dieses Über-/Zurückschwingen,
    // ein schnellerer alphaDecay (Standard ~0.023) lässt die Simulation
    // insgesamt zügiger zur Ruhe kommen statt lange nachzuzittern.
    .velocityDecay(0.55)
    .alphaDecay(0.05);
  currentSimulation = simulation;

  const link = container
    .append('g')
    .selectAll('line')
    .data(edges)
    .join('line')
    .attr('class', 'explore-edge')
    .attr('stroke-width', (d) => Math.min(1 + Math.sqrt(d.weight), 5));

  const node = container
    .append('g')
    .selectAll('g')
    .data(nodes)
    .join('g')
    .attr('class', (d) => `explore-node explore-node--${d.type} explore-node--cluster-${d.cluster % CLUSTER_COLOR_COUNT}`)
    .call(drag(simulation));

  node.append('title').text((d) => d.label);

  let selectedNodeId = null;

  function clearSelection() {
    selectedNodeId = null;
    node.classed('explore-node--dimmed', false);
    node.classed('explore-node--selected', false);
    node.classed('explore-node--show-open-icon', false);
    link.classed('explore-edge--dimmed', false);
  }

  function selectNode(d) {
    selectedNodeId = d.id;
    const visibleIds = neighborIds(d.id, edges);
    node.classed('explore-node--dimmed', (n) => !visibleIds.has(n.id));
    node.classed('explore-node--selected', (n) => n.id === d.id);
    // Nutzerwunsch: das "In neuem Tab öffnen"-Icon erscheint am
    // angeklickten Knoten UND an allen mit ihm hervorgehobenen
    // (nicht gedimmten) Nachbarn - identische Menge wie visibleIds.
    node.classed('explore-node--show-open-icon', (n) => visibleIds.has(n.id));
    link.classed('explore-edge--dimmed', (e) => {
      const sourceId = typeof e.source === 'object' ? e.source.id : e.source;
      const targetId = typeof e.target === 'object' ? e.target.id : e.target;
      return sourceId !== d.id && targetId !== d.id;
    });

    // Nutzerwunsch (2026-08-23): der angeklickte Knoten wandert sanft in
    // die Bildmitte - gleicher Zoom-Faktor wie aktuell, nur die
    // Verschiebung ändert sich, damit ein bereits eingezoomter Zustand
    // erhalten bleibt.
    const currentTransform = d3.zoomTransform(svg.node());
    const targetX = width / 2 - d.x * currentTransform.k;
    const targetY = height / 2 - d.y * currentTransform.k;
    svg
      .transition()
      .duration(500)
      .call(zoomBehavior.transform, d3.zoomIdentity.translate(targetX, targetY).scale(currentTransform.k));
  }

  node.on('click', (event, d) => {
    event.stopPropagation();
    if (selectedNodeId === d.id) {
      clearSelection();
    } else {
      selectNode(d);
    }
  });

  svg.on('click', clearSelection);

  node
    .filter((d) => d.type === 'author' && d.photo_url)
    .append('clipPath')
    .attr('id', (d, i) => `explore-clip-${i}`)
    .append('circle')
    .attr('r', radiusFor);

  node.append('circle').attr('class', 'explore-node-circle').attr('r', radiusFor);

  node
    .filter((d) => d.type === 'author' && d.photo_url)
    .append('image')
    .attr('href', (d) => d.photo_url)
    .attr('x', (d) => -radiusFor(d))
    .attr('y', (d) => -radiusFor(d))
    .attr('width', (d) => radiusFor(d) * 2)
    .attr('height', (d) => radiusFor(d) * 2)
    .attr('preserveAspectRatio', 'xMidYMid slice')
    .attr('clip-path', (d, i) => `url(#explore-clip-${i})`)
    // Nutzerfeedback (2026-08-23): Speicherverbrauch senken - Fotos sind
    // extern frei eingetragene URLs (also potenziell hochauflösend), auch
    // wenn sie hier nur winzig als Kreis erscheinen. lazy/async verzögert
    // das Laden/Dekodieren außerhalb des sichtbaren Bereichs, statt alle
    // ~50 Fotos sofort auf einmal zu dekodieren.
    .attr('loading', 'lazy')
    .attr('decoding', 'async');

  const label = node
    .append('text')
    .attr('class', 'explore-node-label')
    .attr('text-anchor', 'middle')
    .attr('dy', (d) => radiusFor(d) + 12)
    .text((d) => d.label);

  // Nutzerwunsch (2026-08-23): Klick auf einen Knoten hebt ihn nur noch
  // hervor (siehe selectNode weiter unten), statt direkt zu navigieren -
  // ein eigenes "In neuem Tab öffnen"-Icon direkt hinter dem Namen ist der
  // neue, explizite Weg dorthin. Nur an hervorgehobenen Knoten sichtbar
  // (siehe .explore-node--show-open-icon), Position wird nach dem Setzen
  // des Textes per getBBox() gemessen, da SVG-Text kein automatisches
  // Inline-Fließen wie HTML kennt.
  // Nutzerfeedback: Icon war zu groß und saß nicht auf derselben
  // "Zeile" wie die Beschriftung - kleinere Größe, Y-Position an der
  // Text-Baseline ausgerichtet statt an einer groben Pauschalschätzung
  // (Label-Schriftgröße 0.7rem ≈ 11.2px, Großbuchstaben-Mitte liegt grob
  // 35% der Schriftgröße oberhalb der Grundlinie).
  const OPEN_ICON_SIZE = 9;
  const LABEL_FONT_SIZE_PX = 11.2;
  const openIcon = node
    .append('g')
    .attr('class', 'explore-node-open-icon')
    .on('click', (event, d) => {
      event.stopPropagation();
      window.open(nodeUrl(d), '_blank', 'noopener');
    });
  openIcon.append('title').text(t('explore.openInNewTabTitle'));
  // Größere unsichtbare Klickfläche - das reine Icon-Pfad-Rechteck wäre für
  // einen Fingertipp/Mausklick zu klein.
  openIcon
    .append('rect')
    .attr('class', 'explore-node-open-icon-hitbox')
    .attr('x', -5)
    .attr('y', -5)
    .attr('width', OPEN_ICON_SIZE + 10)
    .attr('height', OPEN_ICON_SIZE + 10);
  openIcon
    .append('path')
    .attr('d', 'M5.5 0h3.5v3.5M9 0 4.5 4.5M9 5.5v2.5a1 1 0 0 1-1 1H1a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1h2.5');

  label.each(function (d) {
    d._labelHalfWidth = this.getBBox().width / 2;
  });
  openIcon.attr('transform', (d) => {
    const baselineY = radiusFor(d) + 12;
    const y = baselineY - LABEL_FONT_SIZE_PX * 0.35 - OPEN_ICON_SIZE / 2;
    return `translate(${(d._labelHalfWidth || 0) + 6}, ${y})`;
  });

  function ticked() {
    link
      .attr('x1', (d) => d.source.x)
      .attr('y1', (d) => d.source.y)
      .attr('x2', (d) => d.target.x)
      .attr('y2', (d) => d.target.y);
    node.attr('transform', (d) => `translate(${d.x},${d.y})`);
  }

  if (prefersReducedMotion) {
    // Nutzerwunsch (Barrierefreiheit): keine sichtbare Einschwingphase -
    // Simulation stumm auf die Endposition vorspulen statt zu animieren.
    simulation.stop();
    for (let i = 0; i < 250; i += 1) simulation.tick();
    ticked();
  } else {
    simulation.on('tick', ticked);
  }

  currentSearchHandler = () => {
    const query = normalizeSearch(searchInput.value);
    if (!query) {
      node.classed('explore-node--dimmed', false);
      link.classed('explore-edge--dimmed', false);
      return;
    }
    const matchedIds = new Set(nodes.filter((d) => normalizeSearch(d.label).includes(query)).map((d) => d.id));
    node.classed('explore-node--dimmed', (d) => !matchedIds.has(d.id));
    link.classed('explore-edge--dimmed', (d) => !matchedIds.has(d.source.id) && !matchedIds.has(d.target.id));
  };
  searchInput.addEventListener('input', currentSearchHandler);
}

async function loadGraph() {
  statusEl.textContent = t('explore.loading');
  statusEl.classList.remove('hidden');
  wrapEl.classList.add('hidden');
  searchInput.value = '';
  try {
    const res = await fetch('/api/knowledge-graph', { headers: { 'X-Lang': getLang() } });
    if (!res.ok) throw new Error('request failed');
    const data = await res.json();
    if (!data.nodes.length) {
      statusEl.textContent = t('explore.empty');
      return;
    }
    statusEl.classList.add('hidden');
    wrapEl.classList.remove('hidden');
    renderGraph(data);
  } catch (err) {
    statusEl.textContent = t('explore.loadFailed');
    statusEl.classList.remove('hidden');
  }
}

loadGraph();

// Nutzerfeedback (2026-08-23): das Netzwerk selbst (Knoten-Beschriftungen
// aus key_terms_de/en) blieb beim Sprachwechsel unverändert deutsch - die
// statischen Oberflächentexte (Überschrift, Suchfeld-Platzhalter etc.)
// wurden zwar schon über data-i18n aktualisiert, die Graphdaten aber nie
// neu vom Server geladen. Läuft nach demselben Muster wie import.js.
document.addEventListener('i18n:changed', loadGraph);
