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
const toggleAuthorsBtn = document.getElementById('explore-toggle-authors');
const toggleTermsBtn = document.getElementById('explore-toggle-terms');
const legendEl = document.getElementById('explore-legend');
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

// Nutzerwunsch (2026-08-26): Autor:innen/Schlagworte im Netzwerk unabhängig
// voneinander ein-/ausblendbar machen (siehe toggleAuthorsBtn/toggleTermsBtn
// weiter unten). fullGraphData hält die komplette, unveränderte Antwort
// von /api/knowledge-graph (siehe loadGraph) - jeder Toggle rendert daraus
// neu, statt den Server erneut zu fragen.
let fullGraphData = null;
let showAuthors = true;
let showTerms = true;

// Nutzerwunsch: blendet man alle Schlagworte aus, blieben Autor:innen ohne
// Kanten übrig (im Graphen gibt es bisher nur Autor-Schlagwort- und
// Schlagwort-Schlagwort-Kanten, keine direkten Autor-Autor-Kanten) - das
// wirkte wie unverbundene Punkte statt eines Netzwerks. Zwei Autor:innen
// werden deshalb hier zusätzlich verbunden, wenn sie mindestens ein
// gemeinsames (jetzt ausgeblendetes) Schlagwort teilen, mit der Anzahl
// geteilter Begriffe als Gewicht - dieselbe Co-Occurrence-Logik wie bei den
// bestehenden Schlagwort-Schlagwort-Kanten, nur eine Ebene höher. Bereits
// vorhandene direkte Autor-Autor-Kanten (z.B. durch den Keyword-Autor:innen-
// Merge, wenn eine Person in einem fremden Text als Schlagwort erwähnt
// wird - siehe app/main.py:_build_knowledge_graph) bleiben unverändert
// erhalten und werden nicht doppelt gezählt.
function deriveAuthorOnlyEdges(nodes, edges) {
  const authorIds = new Set(nodes.filter((n) => n.type === 'author').map((n) => n.id));
  const edgeWeights = new Map();
  const bump = (a, b, weight) => {
    const key = [a, b].sort().join('::');
    edgeWeights.set(key, (edgeWeights.get(key) || 0) + weight);
  };
  const authorsByHiddenTerm = new Map();
  edges.forEach((e) => {
    const a = typeof e.source === 'object' ? e.source.id : e.source;
    const b = typeof e.target === 'object' ? e.target.id : e.target;
    const aIsAuthor = authorIds.has(a);
    const bIsAuthor = authorIds.has(b);
    if (aIsAuthor && bIsAuthor) {
      bump(a, b, e.weight);
    } else if (aIsAuthor && !bIsAuthor) {
      if (!authorsByHiddenTerm.has(b)) authorsByHiddenTerm.set(b, new Set());
      authorsByHiddenTerm.get(b).add(a);
    } else if (bIsAuthor && !aIsAuthor) {
      if (!authorsByHiddenTerm.has(a)) authorsByHiddenTerm.set(a, new Set());
      authorsByHiddenTerm.get(a).add(b);
    }
  });
  authorsByHiddenTerm.forEach((authors) => {
    const list = Array.from(authors);
    for (let i = 0; i < list.length; i += 1) {
      for (let j = i + 1; j < list.length; j += 1) {
        bump(list[i], list[j], 1);
      }
    }
  });
  return Array.from(edgeWeights.entries()).map(([key, weight]) => {
    const [source, target] = key.split('::');
    return { source, target, weight };
  });
}

function filterGraphForToggles(data, showAuthors, showTerms) {
  if (showAuthors && showTerms) return data;
  if (!showAuthors && !showTerms) return { nodes: [], edges: [] };
  if (showAuthors) {
    // Autor:innen an, Schlagworte aus.
    const nodes = data.nodes.filter((n) => n.type === 'author');
    return { nodes, edges: deriveAuthorOnlyEdges(data.nodes, data.edges) };
  }
  // Schlagworte an, Autor:innen aus - bestehende Schlagwort-Schlagwort-
  // Kanten bleiben unverändert, nur Kanten zu jetzt ausgeblendeten
  // Autor:innen fallen weg.
  const authorIds = new Set(data.nodes.filter((n) => n.type === 'author').map((n) => n.id));
  const nodes = data.nodes.filter((n) => n.type === 'term');
  const edges = data.edges.filter((e) => {
    const a = typeof e.source === 'object' ? e.source.id : e.source;
    const b = typeof e.target === 'object' ? e.target.id : e.target;
    return !authorIds.has(a) && !authorIds.has(b);
  });
  return { nodes, edges };
}

// Nutzerwunsch (2026-08-27): unscheinbare Erklärung (wie der Bildquellen-
// nachweis in der Autor:innen-Vita, siehe .author-photo-credit) rechts unter
// dem Netzwerk, was Knoten/Kanten bedeuten - ändert sich mit den beiden
// Toggle-Buttons, damit der jeweils sichtbare Netzwerk-Aufbau nachvollziehbar
// bleibt (z.B. dass Autor-Autor-Kanten im Nur-Autor:innen-Modus über
// ausgeblendete Schlagworte abgeleitet sind, siehe deriveAuthorOnlyEdges).
function updateLegend() {
  if (showAuthors && showTerms) {
    legendEl.textContent = t('explore.legendBoth');
  } else if (showAuthors) {
    legendEl.textContent = t('explore.legendAuthorsOnly');
  } else if (showTerms) {
    legendEl.textContent = t('explore.legendTermsOnly');
  }
}

function applyFiltersAndRender() {
  if (!fullGraphData) return;
  const filtered = filterGraphForToggles(fullGraphData, showAuthors, showTerms);
  if (!filtered.nodes.length) {
    currentSimulation?.stop();
    svg.selectAll('*').remove();
    statusEl.textContent = t('explore.emptyFiltered');
    statusEl.classList.remove('hidden');
    wrapEl.classList.add('hidden');
    legendEl.classList.add('hidden');
    return;
  }
  statusEl.classList.add('hidden');
  wrapEl.classList.remove('hidden');
  updateLegend();
  legendEl.classList.remove('hidden');
  renderGraph(filtered);
  // Eine bereits eingetippte Suche soll nach dem Neu-Rendern weiterhin
  // greifen, statt erst beim nächsten Tastendruck wieder aufzuleben.
  if (searchInput.value.trim()) currentSearchHandler?.();
}

toggleAuthorsBtn.addEventListener('click', () => {
  showAuthors = !showAuthors;
  toggleAuthorsBtn.classList.toggle('active', showAuthors);
  toggleAuthorsBtn.setAttribute('aria-pressed', String(showAuthors));
  applyFiltersAndRender();
});

toggleTermsBtn.addEventListener('click', () => {
  showTerms = !showTerms;
  toggleTermsBtn.classList.toggle('active', showTerms);
  toggleTermsBtn.setAttribute('aria-pressed', String(showTerms));
  applyFiltersAndRender();
});

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

// Nutzerwunsch (2026-08-24): Zoom-Transform, die das GESAMTE, bereits
// eingeschwungene Netzwerk zentriert in den sichtbaren Bereich einpasst -
// Ausgangspunkt für den anschließenden Zoom auf die Standard-Zoomstufe
// (siehe renderGraph). PADDING berücksichtigt, dass Knoten-Radius und
// darunter sitzende Beschriftung über die reine x/y-Position hinausragen.
function computeFitTransform(nodes, width, height) {
  const PADDING = 90;
  const xs = nodes.map((d) => d.x);
  const ys = nodes.map((d) => d.y);
  const minX = Math.min(...xs) - PADDING;
  const maxX = Math.max(...xs) + PADDING;
  const minY = Math.min(...ys) - PADDING;
  const maxY = Math.max(...ys) + PADDING;
  const graphWidth = Math.max(maxX - minX, 1);
  const graphHeight = Math.max(maxY - minY, 1);
  // Gedeckelt bei 1: bei einem sehr kleinen Netzwerk soll die Übersicht
  // nicht stärker heranzoomen als die ohnehin schon nahe Standardansicht.
  const scale = Math.min(width / graphWidth, height / graphHeight, 1);
  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;
  return d3.zoomIdentity.translate(width / 2, height / 2).scale(scale).translate(-cx, -cy);
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
  // Netzwerk mit ~300 Knoten erschlagend dicht - Standardansicht ist
  // stattdessen näher herangezoomt, mittig zentriert, ganz normal mit dem
  // Mausrad weiter heraus-/hineinzoombar. Angewendet wird das erst weiter
  // unten, NACH dem synchronen Einschwingen der Simulation (siehe dort).
  // Nutzerfeedback (2026-08-24): 1.8 zoomte nach der neuen "Gesamtübersicht
  // -> Standardansicht"-Animation (siehe unten) zu tief hinein - auf 1.3
  // reduziert, bleibt also "weiter oben".
  const INITIAL_ZOOM_SCALE = 1.3;

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

  const photoImages = node
    .filter((d) => d.type === 'author' && d.photo_url)
    .append('image')
    .attr('x', (d) => -radiusFor(d))
    .attr('y', (d) => -radiusFor(d))
    .attr('width', (d) => radiusFor(d) * 2)
    .attr('height', (d) => radiusFor(d) * 2)
    .attr('preserveAspectRatio', 'xMidYMid slice')
    .attr('clip-path', (d, i) => `url(#explore-clip-${i})`)
    .attr('decoding', 'async');

  // Nutzerfeedback (2026-09-01, echter Absturz auf Mobilgeräten beim
  // Navigieren/Klicken im Netzwerk): `loading="lazy"` (vorherige Fassung,
  // direkt beim Anlegen des <image>-Elements gesetzt) ist eine HTML-<img>-
  // Eigenschaft - SVG-<image> ignoriert sie in praktisch allen Browsern
  // ersatzlos, das gewünschte gestaffelte Laden fand also nie statt. Bei
  // einem vollen Netzwerk (~50 potenziell hochauflösende, extern frei
  // eingetragene Autor:innen-Fotos) wurden dadurch trotz der Absicht im
  // ursprünglichen Kommentar ALLE Fotos sofort UND gleichzeitig dekodiert -
  // auf speicherknappen Mobilgeräten reicht dieser kurze Dekodier-Peak aus,
  // um den ganzen Tab abstürzen zu lassen. Die eigentliche Bild-URL (href)
  // wird deshalb jetzt selbst in kleinen, zeitlich versetzten Gruppen
  // gesetzt statt sofort beim Erzeugen des Elements - der Browser dekodiert
  // dadurch nie mehr als eine Handvoll Fotos gleichzeitig, unabhängig davon,
  // ob sein natives Lazy-Loading für SVG greift oder nicht.
  const PHOTO_LOAD_BATCH_SIZE = 4;
  const PHOTO_LOAD_BATCH_DELAY_MS = 120;
  photoImages.each(function (d, i) {
    const delay = Math.floor(i / PHOTO_LOAD_BATCH_SIZE) * PHOTO_LOAD_BATCH_DELAY_MS;
    setTimeout(() => this.setAttribute('href', d.photo_url), delay);
  });

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

  // Nutzerfeedback (2026-08-24): Die Simulation lief bisher ab alpha=1
  // sichtbar im Browser mit - bei ~300 Knoten/~1700 Kanten wirkte das
  // anfängliche Auseinanderfliegen/Einschwingen wie ein Grafikfehler
  // ("zittert stark"), nicht wie eine bewusste Animation. Jetzt wird die
  // Simulation VOR dem ersten Zeichnen synchron bis zur Ruhelage
  // vorgerechnet (wie zuvor schon nur für prefers-reduced-motion) - der
  // Browser bekommt gleich das fertige, stabile Layout zu sehen. Die
  // Bewegung, die stattdessen sichtbar bleibt, ist ein bewusster, sanfter
  // Zoom von der Gesamtübersicht (computeFitTransform) auf die
  // Standard-Zoomstufe, statt physikalischem Zittern.
  simulation.stop();
  for (let i = 0; i < 250; i += 1) simulation.tick();
  ticked();

  const defaultTransform = d3.zoomIdentity
    .translate(width / 2, height / 2)
    .scale(INITIAL_ZOOM_SCALE)
    .translate(-width / 2, -height / 2);

  if (prefersReducedMotion) {
    // Nutzerwunsch (Barrierefreiheit): keine sichtbare Zoom-Animation -
    // direkt auf die Standard-Zoomstufe springen.
    svg.call(zoomBehavior.transform, defaultTransform);
  } else {
    svg.call(zoomBehavior.transform, computeFitTransform(nodes, width, height));
    // Nutzerwunsch (2026-08-24): Die Gesamtübersicht soll kurz sichtbar
    // stehen bleiben, bevor der Zoom einsetzt (delay), statt sofort
    // loszuzoomen - erst dann wirkt es wie "einmal komplett zeigen, dann
    // hineinzoomen" statt wie ein einziger durchgehender Übergang.
    svg
      .transition()
      .delay(700)
      .duration(900)
      .ease(d3.easeCubicOut)
      .call(zoomBehavior.transform, defaultTransform);
  }

  // Simulation bleibt "warm" (siehe drag()), damit ein gezogener Knoten
  // seine Nachbarn weiterhin sanft nachziehen lässt - nur die anfängliche
  // Einschwingphase wird nicht mehr live mitgerendert.
  simulation.on('tick', ticked);

  // Nutzerwunsch (2026-08-28): Suchtreffer sollen nicht nur hervorgehoben,
  // sondern auch tatsächlich ins sichtbare Fenster gezoomt werden - bisher
  // blieb die Kamera unverändert, ein Treffer außerhalb des aktuellen
  // Ausschnitts war dadurch unsichtbar. Debounced (SEARCH_ZOOM_DEBOUNCE_MS),
  // damit nicht bei jedem einzelnen Tastendruck während des Tippens ein
  // ruckartiger Kameraschwenk ausgelöst wird - die Ab-/Aufdunkelung selbst
  // bleibt sofort/undebounced für direktes Tipp-Feedback. Leere Suche zoomt
  // symmetrisch zurück auf die Standardansicht.
  const SEARCH_ZOOM_DEBOUNCE_MS = 400;
  // Nutzerwunsch (2026-08-28, Folge-Iteration): bei 1-2 Zeichen sind
  // Treffer meist noch zu unspezifisch/zahlreich, um ein sinnvolles Ziel
  // fürs Heranzoomen zu sein - die Ab-/Aufdunkelung bleibt davon unberührt
  // (wirkt weiterhin schon ab dem ersten Zeichen), nur der Kameraschwenk
  // wartet auf mindestens drei Zeichen.
  const MIN_SEARCH_ZOOM_LENGTH = 3;
  let searchZoomTimer = null;

  function zoomTo(transform) {
    svg.transition().duration(600).ease(d3.easeCubicOut).call(zoomBehavior.transform, transform);
  }

  currentSearchHandler = () => {
    const query = normalizeSearch(searchInput.value);
    clearTimeout(searchZoomTimer);
    if (!query) {
      node.classed('explore-node--dimmed', false);
      link.classed('explore-edge--dimmed', false);
      searchZoomTimer = setTimeout(() => zoomTo(defaultTransform), SEARCH_ZOOM_DEBOUNCE_MS);
      return;
    }
    const matchedNodes = nodes.filter((d) => normalizeSearch(d.label).includes(query));
    const matchedIds = new Set(matchedNodes.map((d) => d.id));
    node.classed('explore-node--dimmed', (d) => !matchedIds.has(d.id));
    link.classed('explore-edge--dimmed', (d) => !matchedIds.has(d.source.id) && !matchedIds.has(d.target.id));
    if (matchedNodes.length && query.length >= MIN_SEARCH_ZOOM_LENGTH) {
      searchZoomTimer = setTimeout(() => zoomTo(computeFitTransform(matchedNodes, width, height)), SEARCH_ZOOM_DEBOUNCE_MS);
    }
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
    fullGraphData = data;
    applyFiltersAndRender();
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
