const SVG_NS = "http://www.w3.org/2000/svg";
const METAL_ORDER = ["gold", "silver", "platinum", "palladium"];
const GRAMS_PER_TROY_OZ = 31.1034768;
let currentUnit = "usd"; // "usd" | "inr"

function fmtDate(iso) {
  const d = new Date(iso + "T00:00:00Z");
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

function fmtDateFull(iso) {
  const d = new Date(iso + "T00:00:00Z");
  return d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
}

// x-axis tick labels: "Jun 12" for short ranges, "Jun '26" once the span gets long
// enough that day-level detail stops being useful.
function fmtDateTick(iso, useShort) {
  const d = new Date(iso + "T00:00:00Z");
  if (useShort) {
    const mon = d.toLocaleDateString("en-US", { month: "short", timeZone: "UTC" });
    const yr = d.toLocaleDateString("en-US", { year: "2-digit", timeZone: "UTC" });
    return `${mon} '${yr}`;
  }
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

function fmtMoney(v, unit) {
  if (unit === "inr") {
    return "₹" + Math.round(v).toLocaleString("en-IN");
  }
  return "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// Whole-number variant for the y-axis ticks — cents just add clutter at that size.
function fmtMoneyTick(v, unit) {
  if (unit === "inr") return "₹" + Math.round(v).toLocaleString("en-IN");
  return "$" + Math.round(v).toLocaleString("en-US");
}

function fmtPct(v) {
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  return sign + Math.abs(v).toFixed(2) + "%";
}

function seriesFor(m, unit) {
  return unit === "inr" ? m.inr10g : m.prices;
}
function latestFor(m, unit) {
  return unit === "inr"
    ? { v: m.inrLatest, c1: m.inrChg1d, c7: m.inrChg7d, c30: m.inrChg30d }
    : { v: m.latest, c1: m.chg1d, c7: m.chg7d, c30: m.chg30d };
}

// Single chart — one metal's absolute price history at a time. Superimposing
// all four on one axis made gold's ~$4k scale drown out silver's ~$60, so the
// dropdown swaps the whole series instead of overlaying them.
let selectedMetal = "gold";

const RANGE_PRESETS = [
  { key: "1w", label: "1W", days: 7 },
  { key: "1m", label: "1M", days: 30 },
  { key: "3m", label: "3M", days: 90 },
  { key: "6m", label: "6M", days: 182 },
  { key: "9m", label: "9M", days: 273 },
  { key: "1y", label: "1Y", days: 365 },
  { key: "2y", label: "2Y", days: 730 },
  { key: "3y", label: "3Y", days: 1095 },
  { key: "5y", label: "5Y", days: 1825 },
  { key: "all", label: "ALL", days: null },
];
let selectedRange = "6m";
let customFrom = null;
let customTo = null;

// The full per-metal series is fetched once and cached client-side; every range/metal
// switch just re-slices it in place instead of round-tripping to the API again.
function getRangeSlice(metal, unit) {
  const m = METAL_DATA.metals[metal];
  const dates = m.dates;
  const prices = seriesFor(m, unit);

  if (selectedRange === "custom" && customFrom && customTo) {
    const startIdx = dates.findIndex(d => d >= customFrom);
    let endIdx = -1;
    for (let i = dates.length - 1; i >= 0; i--) {
      if (dates[i] <= customTo) { endIdx = i; break; }
    }
    if (startIdx === -1 || endIdx < startIdx) {
      return { dates: dates.slice(-1), prices: prices.slice(-1) };
    }
    return { dates: dates.slice(startIdx, endIdx + 1), prices: prices.slice(startIdx, endIdx + 1) };
  }

  const preset = RANGE_PRESETS.find(r => r.key === selectedRange) || RANGE_PRESETS[3];
  if (preset.days == null) return { dates, prices };
  const n = Math.min(preset.days, dates.length);
  return { dates: dates.slice(-n), prices: prices.slice(-n) };
}

function drawMetalChart(unit) {
  const svg = document.querySelector(".combo-svg");
  const priceLabel = document.querySelector("[data-combo-price-label]");
  const axisDate = document.querySelector("[data-combo-axis-date]");
  const dot = document.querySelector("[data-combo-dot]");
  if (!svg || !METAL_DATA) return;
  const { dates, prices } = getRangeSlice(selectedMetal, unit);
  const n = dates.length;
  // More headroom at the bottom than the top, so the lowest point of the line
  // never crowds the axis divider below it.
  const W = 600, H = 240, PAD_X = 4, PAD_TOP = 14, PAD_BOTTOM = 32;
  const PRICE_GAP = 22;
  const DOT_RING_RADIUS = 6; // dot radius (4) + its white ring (2), so the pointer stops at the ring, not the dot's center
  const color = `var(--c-${selectedMetal})`;

  const min = Math.min(...prices), max = Math.max(...prices);
  const span = (max - min) || 1;
  const x = i => (i / (n - 1)) * (W - PAD_X * 2) + PAD_X;
  const y = v => (H - PAD_BOTTOM) - ((v - min) / span) * (H - PAD_TOP - PAD_BOTTOM);
  const pts = prices.map((v, i) => [x(i), y(v)]);

  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("preserveAspectRatio", "none");
  svg.innerHTML = "";

  const GRID_ROWS = 4;
  for (let i = 1; i < GRID_ROWS; i++) {
    const gy = PAD_TOP + (i / GRID_ROWS) * (H - PAD_TOP - PAD_BOTTOM);
    const gridLine = document.createElementNS(SVG_NS, "line");
    gridLine.setAttribute("x1", PAD_X); gridLine.setAttribute("x2", W - PAD_X);
    gridLine.setAttribute("y1", gy); gridLine.setAttribute("y2", gy);
    gridLine.setAttribute("stroke", "var(--rule)");
    gridLine.setAttribute("stroke-opacity", "0.6");
    gridLine.setAttribute("vector-effect", "non-scaling-stroke");
    svg.appendChild(gridLine);
  }

  // Axis labels are plain HTML, not SVG text — SVG text would suffer the same
  // non-uniform-scaling distortion the dot used to (preserveAspectRatio="none").
  const axisY = document.querySelector("[data-combo-axis-y]");
  if (axisY) {
    let html = "";
    for (let i = 0; i <= GRID_ROWS; i++) {
      const topPct = ((PAD_TOP + (i / GRID_ROWS) * (H - PAD_TOP - PAD_BOTTOM)) / H) * 100;
      const value = max - (i / GRID_ROWS) * span;
      html += `<div class="combo-axis-y-tick" style="top:${topPct}%">${fmtMoneyTick(value, unit)}</div>`;
    }
    axisY.innerHTML = html;
  }

  const axisX = document.querySelector("[data-combo-axis-x]");
  if (axisX) {
    let html = "";
    if (n > 1) {
      const totalDays = (new Date(dates[n - 1] + "T00:00:00Z") - new Date(dates[0] + "T00:00:00Z")) / 86400000;
      const useShortTick = totalDays > 60;
      const TICK_COUNT = 5;
      for (let i = 0; i < TICK_COUNT; i++) {
        const idx = Math.round((i / (TICK_COUNT - 1)) * (n - 1));
        const leftPct = (idx / (n - 1)) * 100;
        const align = leftPct < 5 ? "translateX(0)" : leftPct > 95 ? "translateX(-100%)" : "translateX(-50%)";
        html += `<div class="combo-axis-x-tick" style="left:${leftPct}%; transform:${align}">${fmtDateTick(dates[idx], useShortTick)}</div>`;
      }
    } else if (n === 1) {
      html = `<div class="combo-axis-x-tick" style="left:50%; transform:translateX(-50%)">${fmtDateTick(dates[0], false)}</div>`;
    }
    axisX.innerHTML = html;
  }

  const defs = document.createElementNS(SVG_NS, "defs");
  const gradId = "grad-" + Math.random().toString(36).slice(2, 9);
  defs.innerHTML = `<linearGradient id="${gradId}" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="${color}" stop-opacity="0.28"/>
    <stop offset="100%" stop-color="${color}" stop-opacity="0"/>
  </linearGradient>`;
  svg.appendChild(defs);

  const linePath = "M" + pts.map(p => p[0].toFixed(2) + "," + p[1].toFixed(2)).join(" L");
  const areaPath = linePath + ` L${pts[pts.length - 1][0].toFixed(2)},${H} L${pts[0][0].toFixed(2)},${H} Z`;

  const area = document.createElementNS(SVG_NS, "path");
  area.setAttribute("d", areaPath);
  area.setAttribute("fill", `url(#${gradId})`);
  area.setAttribute("stroke", "none");
  svg.appendChild(area);

  const line = document.createElementNS(SVG_NS, "path");
  line.setAttribute("d", linePath);
  line.setAttribute("fill", "none");
  line.setAttribute("stroke", color);
  line.setAttribute("stroke-width", "2");
  line.setAttribute("stroke-linejoin", "round");
  line.setAttribute("stroke-linecap", "round");
  line.setAttribute("vector-effect", "non-scaling-stroke");
  svg.appendChild(line);

  const guide = document.createElementNS(SVG_NS, "line");
  guide.setAttribute("y1", "0");
  guide.setAttribute("y2", H);
  guide.setAttribute("stroke", color);
  guide.setAttribute("stroke-opacity", "0.4");
  guide.setAttribute("vector-effect", "non-scaling-stroke");
  guide.style.display = "none";
  svg.appendChild(guide);

  const hit = document.createElementNS(SVG_NS, "rect");
  hit.setAttribute("x", "0");
  hit.setAttribute("y", "0");
  hit.setAttribute("width", W);
  hit.setAttribute("height", H);
  hit.setAttribute("fill", "transparent");
  svg.appendChild(hit);

  function move(evt) {
    const rect = svg.getBoundingClientRect();
    const px = (evt.clientX - rect.left) / rect.width * W;
    let idx = Math.round(((px - PAD_X) / (W - PAD_X * 2)) * (n - 1));
    idx = Math.max(0, Math.min(n - 1, idx));
    const gx = x(idx), gy = y(prices[idx]);
    const leftPct = (gx / W) * 100;
    guide.setAttribute("x1", gx); guide.setAttribute("x2", gx);
    guide.style.display = "block";
    // A plain DOM circle, not an SVG <circle>, so it stays round even though the
    // chart's viewBox is stretched non-uniformly (preserveAspectRatio="none").
    if (dot) {
      dot.style.left = leftPct + "%";
      dot.style.top = (gy / H) * 100 + "%";
      dot.style.display = "block";
    }
    // Price sits to the left of the dot, vertically centered on it. Its pointer (an
    // ::after/::before on the label itself, see CSS) spans the gap to the dot's outer
    // ring; --pointer-len drives its length so the tip always lands exactly on the ring.
    if (priceLabel) {
      priceLabel.textContent = fmtMoney(prices[idx], unit);
      priceLabel.style.left = `calc(${leftPct}% - ${PRICE_GAP}px)`;
      priceLabel.style.top = (gy / H) * 100 + "%";
      priceLabel.style.transform = "translate(-100%, -50%)";
      priceLabel.style.setProperty("--pointer-len", (PRICE_GAP - DOT_RING_RADIUS) + "px");
      priceLabel.style.display = "block";
    }
    // Date sits along the x axis at the bottom, under the guide line.
    if (axisDate) {
      axisDate.textContent = fmtDateFull(dates[idx]);
      axisDate.style.left = leftPct + "%";
      axisDate.style.transform = "translateX(-50%)";
      axisDate.style.display = "block";
    }
  }
  function leave() {
    guide.style.display = "none";
    if (dot) dot.style.display = "none";
    if (priceLabel) priceLabel.style.display = "none";
    if (axisDate) axisDate.style.display = "none";
  }
  svg.onmousemove = move;
  svg.onmouseleave = leave;
  svg.ontouchmove = e => { if (e.touches[0]) move(e.touches[0]); };
  svg.ontouchend = leave;
}

function renderMetalStat(unit) {
  const m = METAL_DATA.metals[selectedMetal];
  document.getElementById("stats").style.setProperty("--metal-color", `var(--c-${selectedMetal})`);
  document.querySelector("[data-combo-fine]").textContent = m.fineness + " FINE";
}

function renderTableView(unit) {
  const tbody = document.querySelector("[data-table-body]");
  if (!tbody) return;
  tbody.innerHTML = METAL_ORDER.map(key => {
    const m = METAL_DATA.metals[key];
    const s = latestFor(m, unit);
    return `<tr><td>${m.label}</td><td>${m.ticker}</td><td>${fmtMoney(s.v, unit)}</td><td>${fmtPct(s.c1)}</td><td>${fmtPct(s.c7)}</td><td>${fmtPct(s.c30)}</td></tr>`;
  }).join("");
}

function updateCombo(unit) {
  currentUnit = unit;
  renderMetalStat(unit);
  drawMetalChart(unit);
  renderTableView(unit);
  document.querySelectorAll(".unit-toggle button").forEach(b => {
    b.classList.toggle("is-active", b.getAttribute("data-unit") === unit);
  });
}

function setActiveRangeButton(key) {
  document.querySelectorAll(".range-btn").forEach(b => {
    b.classList.toggle("is-active", b.getAttribute("data-range") === key);
  });
}

function applyRange(key) {
  selectedRange = key;
  setActiveRangeButton(key);
  document.querySelector("[data-range-custom]").hidden = key !== "custom";
  renderMetalStat(currentUnit);
  drawMetalChart(currentUnit);
}

function initCombo() {
  const select = document.querySelector("[data-metal-select]");
  select.value = selectedMetal;
  select.addEventListener("change", () => {
    selectedMetal = select.value;
    updateCombo(currentUnit);
  });
  document.querySelectorAll(".unit-toggle button").forEach(btn => {
    btn.addEventListener("click", () => updateCombo(btn.getAttribute("data-unit")));
  });
  document.querySelectorAll(".range-btn").forEach(btn => {
    btn.addEventListener("click", () => applyRange(btn.getAttribute("data-range")));
  });

  const fromInput = document.querySelector("[data-range-from]");
  const toInput = document.querySelector("[data-range-to]");
  const bounds = METAL_DATA.metals[selectedMetal].dates;
  fromInput.min = toInput.min = bounds[0];
  fromInput.max = toInput.max = bounds[bounds.length - 1];
  function applyCustomRange() {
    if (fromInput.value && toInput.value && fromInput.value <= toInput.value) {
      customFrom = fromInput.value;
      customTo = toInput.value;
      selectedRange = "custom";
      setActiveRangeButton("custom");
      renderMetalStat(currentUnit);
      drawMetalChart(currentUnit);
    }
  }
  fromInput.addEventListener("change", applyCustomRange);
  toInput.addEventListener("change", applyCustomRange);

  setActiveRangeButton(selectedRange);
  updateCombo(currentUnit);
}

const METAL_META = {
  gold: { label: "Gold", ticker: "XAU", fineness: ".9999" },
  silver: { label: "Silver", ticker: "XAG", fineness: ".999" },
  platinum: { label: "Platinum", ticker: "XPT", fineness: ".9995" },
  palladium: { label: "Palladium", ticker: "XPD", fineness: ".9995" },
};

function pctChange(arr, i, j) {
  if (j < 0 || arr[j] === 0) return 0;
  return Math.round((arr[i] - arr[j]) / arr[j] * 10000) / 100;
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${url} returned ${response.status} ${response.statusText}`);
  }
  return response.json();
}

async function loadLiveData() {
  const metals = Object.keys(METAL_META);
  const metalsData = {};

  // Full daily USD→INR history in one uncapped call — each metal's series is then
  // converted using the actual rate for that specific day, not one rate applied throughout.
  const fxRows = await fetchJson(`/api/fx/inr?start=2000-01-01`);
  const fxByDate = new Map(fxRows.map(r => [r.date, r.rate_to_usd]));

  // Fetch each metal's entire available history once (uncapped via start=) so every
  // range preset and the custom picker can slice locally with no further round-trips.
  for (const m of metals) {
    const usdRows = await fetchJson(`/api/prices/${m}?start=2000-01-01`);
    const dates = usdRows.map(r => r.date);
    const prices = usdRows.map(r => r.price_usd);
    const n = prices.length;

    // Same oz→10g conversion the backend's widget endpoint applies, but paired with
    // each day's own FX rate. Falls back to the last known rate for any missing date,
    // mirroring the backend's own "closest prior date" lookup semantics.
    let lastRate = null;
    const inr10g = prices.map((p, i) => {
      const fx = fxByDate.get(dates[i]);
      if (fx != null) lastRate = fx;
      return lastRate ? Math.round((p / GRAMS_PER_TROY_OZ * 10 / lastRate) * 100) / 100 : null;
    });

    metalsData[m] = {
      ...METAL_META[m],
      dates,
      prices,
      latest: prices[n - 1],
      chg1d: pctChange(prices, n - 1, n - 2),
      chg7d: pctChange(prices, n - 1, n - 8),
      chg30d: pctChange(prices, n - 1, n - 31),
      inr10g,
      inrLatest: inr10g[n - 1],
      inrChg1d: pctChange(inr10g, n - 1, n - 2),
      inrChg7d: pctChange(inr10g, n - 1, n - 8),
      inrChg30d: pctChange(inr10g, n - 1, n - 31),
    };
  }
  window.METAL_DATA = { metals: metalsData };

  initCombo();
}

loadLiveData().catch(err => {
  console.error("Failed to load live prices", err);
  const fineEl = document.querySelector("[data-combo-fine]");
  if (fineEl) fineEl.textContent = "Unable to load price data.";
});

