// MSFS InGamePanel custom element registration
try {
class MacheteChartsPanel extends TemplateElement {
  constructor() {
    super(...arguments);
    this.started = false;
    this.ingameUi = null;
  }
  connectedCallback() {
    super.connectedCallback();
    this.ingameUi = this.querySelector('ingame-ui');
    if (!this.started) {
      this.started = true;
      this.initApp();
    }
  }
  disconnectedCallback() {
    super.disconnectedCallback();
  }
  initApp() {

  let chartsData = null;
  let state = { view: 'home', airport: null, category: null, plate: null };
  const contentEl = document.getElementById('content');
  const searchInput = document.getElementById('searchInput');
  const searchBtn = document.getElementById('searchBtn');
  const searchResults = document.getElementById('searchResults');

  // MSFS Coherent GT: redirect keyboard input to panel when input is focused
  searchInput.addEventListener('focus', function () {
    try { Coherent.trigger('FOCUS_INPUT_FIELD', '', '', '', ''); } catch(e) {}
  });
  searchInput.addEventListener('blur', function () {
    try { Coherent.trigger('UNFOCUS_INPUT_FIELD', '', '', '', ''); } catch(e) {}
  });

  // Load charts.json — try coui:// (MSFS), then relative (local dev), then remote fallback
  const chartsUrls = [
    'coui://html_ui/InGamePanels/MacheteCharts/charts.json',
    'charts.json',
    'https://hermes-tv.com/MacheteCharts/charts.json'
  ];
  (function tryLoad(i) {
    if (i >= chartsUrls.length) {
      contentEl.innerHTML = '<div class="empty-state"><h2>Error</h2><p>Could not load chart index.</p></div>';
      return;
    }
    fetch(chartsUrls[i])
      .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(data => {
        chartsData = data;
        console.log('Loaded ' + Object.keys(data).length + ' airports from ' + chartsUrls[i]);
      })
      .catch(err => {
        console.warn('charts.json load failed from ' + chartsUrls[i] + ': ' + err);
        tryLoad(i + 1);
      });
  })(0);

  // Search input handling
  searchInput.addEventListener('input', onSearchInput);
  searchInput.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') {
      doSearch();
    }
  });
  searchBtn.addEventListener('click', doSearch);

  // Close dropdown when clicking outside
  document.addEventListener('click', function (e) {
    if (!e.target.closest('.search-wrapper')) {
      searchResults.classList.remove('visible');
    }
  });

  // Strip ICAO K-prefix to get FAA identifier (KBOS -> BOS)
  function normalizeCode(q) {
    if (q.length === 4 && q.startsWith('K') && !chartsData[q]) {
      return q.substring(1);
    }
    return q;
  }

  function onSearchInput() {
    let q = searchInput.value.trim().toUpperCase();
    if (!chartsData || q.length === 0) {
      searchResults.classList.remove('visible');
      return;
    }

    const qNorm = normalizeCode(q);
    const matches = [];
    for (const code in chartsData) {
      const airport = chartsData[code];
      if (code.startsWith(qNorm) || code.includes(qNorm) ||
          code.startsWith(q) || airport.name.toUpperCase().includes(q)) {
        matches.push(airport);
        if (matches.length >= 15) break;
      }
    }

    if (matches.length === 0) {
      searchResults.classList.remove('visible');
      return;
    }

    searchResults.innerHTML = matches.map(a =>
      `<div class="search-result-item" data-code="${a.code}">` +
      `<span class="result-code">${a.code}</span>` +
      `<span class="result-name">${a.name}</span>` +
      `</div>`
    ).join('');
    searchResults.classList.add('visible');

    searchResults.querySelectorAll('.search-result-item').forEach(el => {
      el.addEventListener('click', function () {
        selectAirport(this.dataset.code);
        searchResults.classList.remove('visible');
      });
    });
  }

  function doSearch() {
    let q = searchInput.value.trim().toUpperCase();
    searchResults.classList.remove('visible');
    if (!chartsData || !q) return;

    const qNorm = normalizeCode(q);

    // Exact match (try normalized first, then raw)
    if (chartsData[qNorm]) {
      selectAirport(qNorm);
      return;
    }
    if (chartsData[q]) {
      selectAirport(q);
      return;
    }

    // Partial match
    for (const code in chartsData) {
      if (code.includes(qNorm) || code.includes(q) ||
          chartsData[code].name.toUpperCase().includes(q)) {
        selectAirport(code);
        return;
      }
    }

    contentEl.innerHTML = '<div class="empty-state"><p>No airport found for "' + escapeHtml(q) + '"</p></div>';
  }

  function selectAirport(code) {
    const airport = chartsData[code];
    if (!airport) return;
    state = { view: 'airport', airport: code, category: null, plate: null };
    searchInput.value = code;
    renderAirport(airport);
  }

  function renderAirport(airport) {
    const cats = airport.plates;
    const catLabels = {
      diagram: 'Airport Diagram',
      approach: 'Approaches',
      departure: 'Departures',
      star: 'STARs'
    };
    const catOrder = ['diagram', 'approach', 'departure', 'star'];

    let html = `<div class="airport-info">
      <h2>${escapeHtml(airport.name)}</h2>
      <div class="code">${airport.code}</div>
    </div>`;

    html += '<div class="categories">';
    for (const cat of catOrder) {
      if (!cats[cat] || cats[cat].length === 0) continue;
      const count = cats[cat].length;
      if (cat === 'diagram' && count === 1) {
        // Single diagram - go directly to viewer
        html += `<div class="cat-btn" data-action="viewplate" data-cat="diagram" data-idx="0">` +
          `${catLabels[cat]}<span class="count">1 chart</span></div>`;
      } else {
        html += `<div class="cat-btn" data-action="category" data-cat="${cat}">` +
          `${catLabels[cat]}<span class="count">${count} chart${count > 1 ? 's' : ''}</span></div>`;
      }
    }
    html += '</div>';

    contentEl.innerHTML = html;

    contentEl.querySelectorAll('[data-action="category"]').forEach(el => {
      el.addEventListener('click', function () {
        showCategory(airport, this.dataset.cat);
      });
    });

    contentEl.querySelectorAll('[data-action="viewplate"]').forEach(el => {
      el.addEventListener('click', function () {
        const cat = this.dataset.cat;
        const idx = parseInt(this.dataset.idx);
        showPlate(airport, cat, idx);
      });
    });
  }

  function showCategory(airport, cat) {
    state.view = 'category';
    state.category = cat;

    const catLabels = { diagram: 'Airport Diagram', approach: 'Approaches', departure: 'Departures', star: 'STARs' };
    const plates = airport.plates[cat] || [];

    let html = `<button class="back-btn" id="backToAirport">&larr; ${airport.code}</button>`;
    html += `<div class="airport-info"><h2>${catLabels[cat]}</h2></div>`;
    html += '<div class="plate-list">';
    plates.forEach((plate, idx) => {
      html += `<div class="plate-item" data-idx="${idx}">` +
        `<span class="plate-name">${escapeHtml(plate.name)}</span><span class="page-num">${plate.page}</span></div>`;
    });
    html += '</div>';

    contentEl.innerHTML = html;

    document.getElementById('backToAirport').addEventListener('click', function () {
      renderAirport(airport);
    });

    contentEl.querySelectorAll('.plate-item').forEach(el => {
      el.addEventListener('click', function () {
        showPlate(airport, cat, parseInt(this.dataset.idx));
      });
    });
  }

  function showPlate(airport, cat, idx) {
    const plate = airport.plates[cat][idx];
    const page = plate.page;
    state.view = 'plate';
    state.plate = page;

    // Determine image path (remote-hosted)
    const imgSrc = 'https://hermes-tv.com/MacheteCharts/charts/' + page.toLowerCase() + '.jpg';

    // Build plate viewer overlay
    const viewer = document.createElement('div');
    viewer.className = 'plate-viewer';
    viewer.innerHTML =
      `<div class="plate-toolbar">` +
      `<button id="plateBack">&larr; Back</button>` +
      `<span class="title">${escapeHtml(plate.name)}</span>` +
      `<button id="plateZoomOut">&minus;</button>` +
      `<button id="plateZoomIn">+</button>` +
      `<button id="plateReset">Fit</button>` +
      `</div>` +
      `<div class="plate-container" id="plateContainer">` +
      `<div id="plateLoading" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#ccc;font-size:1.2em;">Loading...</div>` +
      `<img id="plateImg" src="${imgSrc}" alt="${escapeHtml(plate.name)}" style="opacity:0;transition:opacity .2s">` +
      `</div>`;

    document.getElementById('app').appendChild(viewer);

    const img = document.getElementById('plateImg');
    const container = document.getElementById('plateContainer');

    let scale = 1;
    let panX = 0;
    let panY = 0;

    function applyTransform() {
      img.style.transform = `translate(${panX}px, ${panY}px) scale(${scale})`;
    }

    function fitImage() {
      const cw = container.clientWidth;
      const ch = container.clientHeight;
      const iw = img.naturalWidth;
      const ih = img.naturalHeight;
      if (iw === 0 || ih === 0) return;
      scale = Math.min(cw / iw, ch / ih);
      panX = (cw - iw * scale) / 2;
      panY = (ch - ih * scale) / 2;
      applyTransform();
    }

    img.addEventListener('load', function () {
      document.getElementById('plateLoading').style.display = 'none';
      img.style.opacity = '1';
      fitImage();
    });
    img.addEventListener('error', function () {
      var el = document.getElementById('plateLoading');
      if (el) el.innerHTML = 'Failed to load chart image.';
    });
    if (img.complete && img.naturalWidth > 0) {
      document.getElementById('plateLoading').style.display = 'none';
      img.style.opacity = '1';
      fitImage();
    }

    // Pan with mouse drag
    let dragging = false;
    let lastX = 0, lastY = 0;

    container.addEventListener('mousedown', function (e) {
      dragging = true;
      lastX = e.clientX;
      lastY = e.clientY;
      e.preventDefault();
    });

    container.addEventListener('mousemove', function (e) {
      if (!dragging) return;
      panX += e.clientX - lastX;
      panY += e.clientY - lastY;
      lastX = e.clientX;
      lastY = e.clientY;
      applyTransform();
    });

    container.addEventListener('mouseup', function () { dragging = false; });
    container.addEventListener('mouseleave', function () { dragging = false; });

    // Zoom with mouse wheel
    container.addEventListener('wheel', function (e) {
      e.preventDefault();
      const rect = container.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;

      const oldScale = scale;
      const delta = e.deltaY > 0 ? 0.9 : 1.1;
      scale = Math.max(0.1, Math.min(10, scale * delta));

      // Zoom toward mouse position
      panX = mx - (mx - panX) * (scale / oldScale);
      panY = my - (my - panY) * (scale / oldScale);
      applyTransform();
    });

    // Touch pan/zoom
    let touches = {};
    let lastPinchDist = 0;

    container.addEventListener('touchstart', function (e) {
      e.preventDefault();
      for (const t of e.changedTouches) {
        touches[t.identifier] = { x: t.clientX, y: t.clientY };
      }
      if (Object.keys(touches).length === 2) {
        const pts = Object.values(touches);
        lastPinchDist = Math.hypot(pts[1].x - pts[0].x, pts[1].y - pts[0].y);
      }
    });

    container.addEventListener('touchmove', function (e) {
      e.preventDefault();
      const ids = Object.keys(touches);

      if (ids.length === 1) {
        // Single finger pan
        const t = e.changedTouches[0];
        const prev = touches[t.identifier];
        if (prev) {
          panX += t.clientX - prev.x;
          panY += t.clientY - prev.y;
          touches[t.identifier] = { x: t.clientX, y: t.clientY };
          applyTransform();
        }
      } else if (ids.length === 2) {
        // Pinch zoom
        for (const t of e.changedTouches) {
          touches[t.identifier] = { x: t.clientX, y: t.clientY };
        }
        const pts = Object.values(touches);
        const dist = Math.hypot(pts[1].x - pts[0].x, pts[1].y - pts[0].y);

        if (lastPinchDist > 0) {
          const rect = container.getBoundingClientRect();
          const cx = (pts[0].x + pts[1].x) / 2 - rect.left;
          const cy = (pts[0].y + pts[1].y) / 2 - rect.top;

          const oldScale = scale;
          scale = Math.max(0.1, Math.min(10, scale * (dist / lastPinchDist)));
          panX = cx - (cx - panX) * (scale / oldScale);
          panY = cy - (cy - panY) * (scale / oldScale);
          applyTransform();
        }
        lastPinchDist = dist;
      }
    });

    container.addEventListener('touchend', function (e) {
      for (const t of e.changedTouches) {
        delete touches[t.identifier];
      }
      if (Object.keys(touches).length < 2) lastPinchDist = 0;
    });

    // Double-click/tap to zoom in
    container.addEventListener('dblclick', function (e) {
      const rect = container.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;

      const oldScale = scale;
      scale = Math.min(10, scale * 1.5);
      panX = mx - (mx - panX) * (scale / oldScale);
      panY = my - (my - panY) * (scale / oldScale);
      applyTransform();
    });

    // Back button
    document.getElementById('plateBack').addEventListener('click', function () {
      viewer.remove();
      if (state.category) {
        showCategory(airport, state.category);
      } else {
        renderAirport(airport);
      }
    });

    // Zoom helper: zoom toward center of viewport
    function zoomByFactor(factor) {
      const rect = container.getBoundingClientRect();
      const cx = rect.width / 2;
      const cy = rect.height / 2;
      const oldScale = scale;
      scale = Math.max(0.1, Math.min(10, scale * factor));
      panX = cx - (cx - panX) * (scale / oldScale);
      panY = cy - (cy - panY) * (scale / oldScale);
      applyTransform();
    }

    // Zoom +/- buttons
    document.getElementById('plateZoomIn').addEventListener('click', function () {
      zoomByFactor(1.3);
    });
    document.getElementById('plateZoomOut').addEventListener('click', function () {
      zoomByFactor(1 / 1.3);
    });

    // Reset/Fit button
    document.getElementById('plateReset').addEventListener('click', fitImage);
  }

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  } // end initApp
} // end class

window.customElements.define('machete-charts-panel', MacheteChartsPanel);
checkAutoload();
} catch(e) { console.error('MacheteChartsPanel error:', e); }
