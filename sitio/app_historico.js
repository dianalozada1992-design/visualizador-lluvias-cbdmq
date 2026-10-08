/* Pagina 2: historico de lluvias y emergencias por dia o rango de fechas.
   Datos: datos/historico.js (parroquias, emergencias) y datos/diario.js (lluvia diaria de 107 estaciones, 2018-2026). */
"use strict";
const H = window.HISTORICO, D = window.DIARIO;
const mapaH = mapaBase("mapa-h");
const D0 = new Date(D.inicio + "T00:00:00");
const UNDIA = 864e5;
const idxDe = s => Math.round((new Date(s + "T00:00:00") - D0) / UNDIA);
const fechaDe = i => { const f = new Date(D0.getTime() + i * UNDIA); return f.toISOString().slice(0, 10); };
const fechaLarga = s => { const f = new Date(s + "T00:00:00"); return `${DIAS_SEM[f.getDay()]} ${f.getDate()} de ${["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"][f.getMonth()]} de ${f.getFullYear()}`; };
const ULTIMO = D.n_dias - 1;
const INTENS = [["Sin lluvia", 0.2, "#e3f4e6"], ["Ligera", 5, "#a8dcae"], ["Moderada", 10, "#5bbfa8"], ["Fuerte", 20, "#2f86c8"], ["Muy fuerte", 30, "#1f5fae"], ["Extrema", Infinity, "#173f8f"]];
const claseH = v => INTENS.find(c => v < c[1]);

// ---------------------------------------------------------------- estaciones y referencia de cada parroquia
const EST = D.estaciones.map((e, i) => ({ ...e, i }));
const dist = (la1, lo1, la2, lo2) => 111.2 * Math.hypot(la1 - la2, (lo1 - lo2) * Math.cos(la1 * Math.PI / 180));
const PARR = H.parroquias.map(p => {
  const f = CAPAS.parroquias.features.find(x => x.properties.id === p.id);
  const la = f ? f.properties.lat : null, lo = f ? f.properties.lon : null;
  const cand = EST.map(e => ({ e, km: dist(la, lo, e.la, e.lo) })).filter(c => c.km <= 12).sort((a, b) => a.km - b.km);
  const ref = EST.find(e => e.n === p.estacion);
  if (ref) cand.unshift({ e: ref, km: dist(la, lo, ref.la, ref.lo) });
  return { ...p, lat: la, lon: lo, cand };
});
// estacion de referencia para el rango: la primera candidata con datos en al menos la mitad de los dias
function referencia(p, i0, i1) {
  for (const c of p.cand) {
    let n = 0; for (let i = i0; i <= i1; i++) if (c.e.d[i] >= 0) n++;
    if (n >= Math.max(1, (i1 - i0 + 1) * 0.5)) return c;
  }
  return null;
}
const EVENTOS = H.eventos.map(e => ({ la: e[0], lo: e[1], fecha: e[2], i: idxDe(e[2]), causa: e[3], parroquia: e[4], barrio: e[5] || "", hora: e[6] || "" }));

// ---------------------------------------------------------------- filtros
const fD = document.getElementById("f-desde"), fH = document.getElementById("f-hasta"), fB = document.getElementById("f-brigada"),
      fP = document.getElementById("f-parroquia"), fC = document.getElementById("f-criticos");
[fD, fH].forEach(x => { x.min = D.inicio; x.max = fechaDe(ULTIMO); });
fD.value = fechaDe(Math.max(0, ULTIMO - 364)); fH.value = fechaDe(ULTIMO);
const brigadasH = [...new Set(H.parroquias.map(p => reparar(p.brigada)))].filter(Boolean).sort();
fB.innerHTML = `<option value="">Todas</option>` + brigadasH.map(b => `<option>${b}</option>`).join("");
function opcionesParroquia() {
  const lst = PARR.filter(p => !fB.value || reparar(p.brigada) === fB.value).sort((a, b) => a.nombre.localeCompare(b.nombre));
  const actual = fP.value;
  fP.innerHTML = `<option value="">Todas</option>` + lst.map(p => `<option value="${p.id}">${p.nombre}</option>`).join("");
  if (lst.some(p => p.id === actual)) fP.value = actual;
}
opcionesParroquia();
const porDia = {}; EVENTOS.forEach(e => porDia[e.fecha] = (porDia[e.fecha] || 0) + 1);
fC.innerHTML = `<option value="">Elegir…</option>` + Object.entries(porDia).sort((a, b) => b[1] - a[1]).slice(0, 40)
  .map(([f, n]) => `<option value="${f}">${f} · ${n} emergencias</option>`).join("");
document.getElementById("periodo-nota").textContent = `Datos disponibles del ${D.inicio} al ${fechaDe(ULTIMO)}. ${H.nota} ` +
  "La lluvia de cada parroquia viene de su estación de referencia (la más cercana con datos en el período)." +
  ((D.descartados || []).length ? ` Se descartaron ${D.descartados.length} datos diarios de más de 60 mm sin respaldo de estaciones vecinas (${D.descartados.map(x => x[0].split(" ")[0] + " " + x[1]).join(", ")}).` : "");

// ---------------------------------------------------------------- mapa
let capaH = L.geoJSON(null).addTo(mapaH), capaEstH = L.layerGroup().addTo(mapaH), capaEventos = L.layerGroup().addTo(mapaH);
L.geoJSON(CAPAS.brigadas, { style: { color: "#1f3f73", weight: 2, fill: false }, interactive: false }).addTo(mapaH);
const graficos = {};
function grafico(id, cfg) { if (graficos[id]) graficos[id].destroy(); graficos[id] = new Chart(document.getElementById(id), cfg); }
const v10 = x => x >= 0 ? x / 10 : null;

function resumenEstacion(e, i0, i1) {
  let tot = 0, n = 0, maxd = -1, idmax = -1, maxh = -1, idh = -1;
  for (let i = i0; i <= i1; i++) {
    if (e.d[i] >= 0) { tot += e.d[i]; n++; if (e.d[i] > maxd) { maxd = e.d[i]; idmax = i; } }
    if (e.h && e.h[i] > maxh) { maxh = e.h[i]; idh = i; }
  }
  return { total: n ? tot / 10 : null, dias: n, max_dia: maxd >= 0 ? maxd / 10 : null, fecha_max: idmax >= 0 ? fechaDe(idmax) : "",
           max_h: maxh >= 0 ? maxh / 10 : null, fecha_max_h: idh >= 0 ? fechaDe(idh) : "" };
}
function escalaLluvia(ndias) {
  // un dia: escala diaria; varios dias: la misma escala multiplicada para el total del periodo
  if (ndias === 1) return CLASES_DIA;
  const k = Math.max(1, Math.round(ndias * 0.35));
  return [[1 * k, "#e3f4e6", `menos de ${fmt(k, 0)} mm`], [5 * k, "#a8dcae", `${fmt(k, 0)}–${fmt(5 * k, 0)}`], [10 * k, "#5bbfa8", `${fmt(5 * k, 0)}–${fmt(10 * k, 0)}`],
          [20 * k, "#2f86c8", `${fmt(10 * k, 0)}–${fmt(20 * k, 0)}`], [Infinity, "#173f8f", `más de ${fmt(20 * k, 0)} mm`]];
}

function actualizarHistorico() {
  let i0 = Math.max(0, Math.min(ULTIMO, idxDe(fD.value || D.inicio))), i1 = Math.max(0, Math.min(ULTIMO, idxDe(fH.value || fechaDe(ULTIMO))));
  if (i1 < i0) [i0, i1] = [i1, i0];
  const nd = i1 - i0 + 1, unDia = nd === 1;
  const sel = PARR.filter(p => (!fB.value || reparar(p.brigada) === fB.value) && (!fP.value || p.id === fP.value));
  const selIds = new Set(sel.map(p => p.id));
  const evs = EVENTOS.filter(e => e.i >= i0 && e.i <= i1 && selIds.has(e.parroquia));
  // por parroquia
  const res = {};
  PARR.forEach(p => {
    const ref = referencia(p, i0, i1);
    const r = { p, ref, emerg: 0, clases: Object.fromEntries(INTENS.map(c => [c[0], [0, 0, 0]])), fuertes: 0, fuertesCon: 0 };
    const ePorDia = {};
    EVENTOS.forEach(e => { if (e.parroquia === p.id && e.i >= i0 && e.i <= i1) { r.emerg++; ePorDia[e.i] = (ePorDia[e.i] || 0) + 1; } });
    if (ref) {
      Object.assign(r, resumenEstacion(ref.e, i0, i1));
      if (ref.e.h) for (let i = i0; i <= i1; i++) { const h = ref.e.h[i]; if (h < 0) continue;
        const c = claseH(h / 10)[0]; const ne = ePorDia[i] || 0;
        r.clases[c][0]++; if (ne) r.clases[c][1]++; r.clases[c][2] += ne;
        if (h >= 100) { r.fuertes++; if (ne) r.fuertesCon++; } }
    }
    r.ePorDia = ePorDia;
    res[p.id] = r;
  });
  // ---- cifras
  const lluviaEvento = e => { const r = res[e.parroquia]; if (!r || !r.ref) return null; return { d: v10(r.ref.e.d[e.i]), h: r.ref.e.h ? v10(r.ref.e.h[e.i]) : null, est: r.ref.e.n }; };
  const evConH = evs.map(lluviaEvento).filter(x => x && x.h !== null);
  const conFuerte = evConH.filter(x => x.h >= 10).length;
  const estRes = EST.map(e => ({ e, r: resumenEstacion(e, i0, i1) })).filter(x => x.r.dias > 0);
  const maxDia = estRes.reduce((a, x) => (x.r.max_dia ?? -1) > (a ? a.r.max_dia : -1) ? x : a, null);
  const maxH = estRes.reduce((a, x) => (x.r.max_h ?? -1) > (a ? a.r.max_h : -1) ? x : a, null);
  const fuertes = sel.reduce((s, p) => s + res[p.id].fuertes, 0), fuertesCon = sel.reduce((s, p) => s + res[p.id].fuertesCon, 0);
  const lugar = fP.value ? sel[0].nombre : fB.value ? "la brigada " + fB.value : "todo el DMQ";
  const periodo = unDia ? fechaLarga(fechaDe(i0)) : `${fechaDe(i0)} a ${fechaDe(i1)} (${nd} días)`;
  document.getElementById("cifras-historico").innerHTML = [
    [fmt(evs.length, 0), `emergencias por lluvia en ${lugar}`, periodo],
    [maxDia ? fmt(maxDia.r.max_dia) + " mm" : "—", unDia ? "lluvia más alta del día" : "lluvia más alta en un día", maxDia ? `${maxDia.e.n}${unDia ? "" : " · " + maxDia.r.fecha_max}` : ""],
    [maxH ? fmt(maxH.r.max_h) + " mm" : "—", "lluvia más intensa en una hora", maxH ? `${maxH.e.n}${unDia ? "" : " · " + maxH.r.fecha_max_h}` : ""],
    [`${estRes.filter(x => x.r.max_dia >= 20).length} de ${estRes.length}`, unDia ? "estaciones con 20 mm o más ese día" : "estaciones con algún día de 20 mm o más", "estaciones con datos en el período"],
    [evConH.length ? fmt(conFuerte / evConH.length * 100, 0) + " %" : "—", "de las emergencias tuvieron lluvia fuerte (≥10 mm en 1 h)", `en la estación de su parroquia ese día${fuertes ? ` · ${fmt(fuertesCon / fuertes * 100, 0)} % de días fuertes con emergencia` : ""}`],
  ].map(c => `<div class="cifra"><div class="valor">${c[0]}</div><div class="rotulo">${c[1]}</div><div class="detalle">${c[2]}</div></div>`).join("");

  // ---- mapa: parroquias
  const ind = estado.indicador, esc = escalaLluvia(nd);
  const maxE = Math.max(1, ...sel.map(p => res[p.id].emerg));
  const palE = ["#ffffff", "#c3e6c6", "#86cdb0", "#4ea8c9", "#2b6fb5", "#173f8f"];
  const cortesE = maxE <= 5 ? [0, 1, 2, 3, 4, 5].map(x => x) : [0, 1, .15, .35, .6, 1.01].map((f, k) => k < 2 ? f : Math.ceil(f * maxE));
  const colE = v => v <= 0 ? palE[0] : palE[Math.min(5, Math.max(1, cortesE.findIndex(x => v < x)))] || palE[5];
  const valor = r => ind === "emergencias" ? r.emerg : ind === "lluvia" ? r.total : r.max_h;
  mapaH.removeLayer(capaH);
  capaH = L.geoJSON(CAPAS.parroquias, {
    style: f => { const r = res[f.properties.id]; const v = r ? valor(r) : null; const s = selIds.has(f.properties.id);
      const fc = ind === "emergencias" ? colE(v || 0) : v === null || v === undefined ? "#f4f6f8" : ind === "lluvia" ? color(v, esc) : color(v, CLASES_AHORA.lluvia_1h.map((c, k) => [[0.2, 5, 10, 20, 30, Infinity][k] || Infinity, c[1], c[2]]));
      return { fillColor: fc, fillOpacity: s ? .8 : .2, color: s && sel.length < 65 ? "#1f3f73" : "#fff", weight: s && sel.length < 65 ? 2 : .7 }; },
    onEachFeature: (f, l) => {
      const r = res[f.properties.id];
      l.bindTooltip(`<b>${f.properties.nombre}</b><br>Emergencias: ${r ? r.emerg : 0}` + (r && r.ref ?
        `<br>Lluvia${unDia ? " del día" : " del período"}: ${fmt(r.total)} mm<br>Máx. en 1 hora: ${fmt(r.max_h)} mm<br><span style="color:#5d6d7e">Estación: ${r.ref.e.n} (${fmt(r.ref.km)} km)</span>` : "<br>Sin estación con datos"), { sticky: true });
      l.on("click", () => { fB.value = reparar(f.properties.brigada || ""); opcionesParroquia(); fP.value = f.properties.id; actualizarHistorico(); });
    } }).addTo(mapaH);
  capaH.bringToBack();
  const titulos = { emergencias: "Emergencias en el período", lluvia: unDia ? "Lluvia del día (mm)" : "Lluvia total del período (mm)", maxh: "Lluvia máxima en 1 hora (mm)" };
  document.getElementById("leyenda-h").innerHTML = `<b>Parroquias: ${titulos[ind]}</b>` + (ind === "emergencias" ?
    palE.slice(1).map((c, k) => `<span class="caja"><i style="background:${c}"></i>${maxE <= 5 ? k + 1 : (k === 0 ? "1" : fmt(cortesE[k], 0) + "+")}</span>`).join("") :
    (ind === "lluvia" ? esc : [[0, "#e3f4e6", "<0,2"], [0, "#a8dcae", "0,2–5"], [0, "#5bbfa8", "5–10"], [0, "#2f86c8", "10–20"], [0, "#173f8f", "20 o más"]]).map(c => `<span class="caja"><i style="background:${c[1]}"></i>${c[2]}</span>`).join(""));
  // ---- mapa: estaciones
  capaEstH.clearLayers();
  if (document.getElementById("ver-est-h").checked) estRes.forEach(({ e, r }) => {
    const m = L.circleMarker([e.la, e.lo], { radius: e.r === "CBDMQ" ? 8 : 6, fillColor: color(r.total, esc), fillOpacity: .95,
      color: e.r === "CBDMQ" ? "#7d3c98" : e.r === "REMMAQ" ? "#117a65" : "#1f3f73", weight: e.r === "CBDMQ" ? 2.5 : 1.3 });
    m.bindTooltip(`<b>${e.n}</b> (${e.r})<br>${unDia ? "Lluvia del día" : "Lluvia del período"}: ${fmt(r.total)} mm` + (r.max_h !== null ? `<br>Máx. en 1 hora: ${fmt(r.max_h)} mm` : "") +
      (unDia ? "" : `<br>Día más lluvioso: ${fmt(r.max_dia)} mm (${r.fecha_max})`) + `<br><span style="color:#5d6d7e">${r.dias} día(s) con dato</span>`);
    capaEstH.addLayer(m);
  });
  document.getElementById("leyenda-h2").innerHTML = `<b>Estaciones: ${unDia ? "lluvia del día" : "lluvia del período"}</b>` + esc.map(c => `<span class="caja"><i class="circulo" style="background:${c[1]}"></i>${c[2]}</span>`).join("") +
    '<span class="caja"><i class="circulo" style="border:2.5px solid #7d3c98"></i>CBDMQ</span><span class="caja"><i class="circulo" style="border:1.5px solid #1f3f73"></i>EPMAPS</span><span class="caja"><i class="circulo" style="border:1.5px solid #117a65"></i>REMMAQ</span>' +
    '<span class="caja"><i style="background:#c0392b;width:10px;height:10px;transform:rotate(45deg)"></i>Emergencia</span>';
  // ---- mapa: emergencias
  capaEventos.clearLayers();
  if (document.getElementById("ver-eventos").checked) evs.forEach(e => {
    const ll = lluviaEvento(e);
    capaEventos.addLayer(L.marker([e.la, e.lo], { icon: L.divIcon({ className: "", html: '<div style="width:9px;height:9px;background:#c0392b;border:1px solid #fff;transform:rotate(45deg)"></div>', iconSize: [9, 9] }) })
      .bindTooltip(`<b>${e.fecha}${e.hora ? " " + e.hora : ""}</b> · ${e.causa}<br>${e.barrio} (${(PARR.find(p => p.id === e.parroquia) || {}).nombre || e.parroquia})` +
        (ll ? `<br>Lluvia ese día: ${fmt(ll.d)} mm · máx. 1 h: ${fmt(ll.h)} mm<br><span style="color:#5d6d7e">${ll.est}</span>` : "")));
  });
  if (fP.value) { const f = CAPAS.parroquias.features.find(x => x.properties.id === fP.value); if (f) mapaH.fitBounds(L.geoJSON(f).getBounds(), { maxZoom: 13 }); }

  // ---- serie temporal (dia, mes o anio segun el largo del periodo)
  const gran = nd <= 120 ? "dia" : nd <= 1100 ? "mes" : "anio";
  const clave = i => gran === "dia" ? fechaDe(i) : gran === "mes" ? fechaDe(i).slice(0, 7) : fechaDe(i).slice(0, 4);
  const grupos = {};
  for (let i = i0; i <= i1; i++) {
    const k = clave(i); const g = grupos[k] = grupos[k] || { e: 0, maxh: null, lluvia: [], fuertes: 0, n: 0 };
    sel.forEach(p => { const r = res[p.id]; g.e += r.ePorDia[i] || 0;
      if (r.ref) { const d = r.ref.e.d[i], h = r.ref.e.h ? r.ref.e.h[i] : -1;
        if (d >= 0) g.lluvia.push(d / 10); if (h >= 0) { g.maxh = Math.max(g.maxh ?? 0, h / 10); if (h >= 100) g.fuertes++; } g.n++; } });
  }
  const ks = Object.keys(grupos);
  const prom = a => a.length ? a.reduce((x, y) => x + y, 0) / a.length : null;
  document.getElementById("titulo-serie").textContent = unDia ? `Lluvia y emergencias del ${fechaLarga(fechaDe(i0))}` : `Lluvia y emergencias ${gran === "dia" ? "día a día" : gran === "mes" ? "mes a mes" : "año a año"}`;
  if (unDia) {
    // un dia: lluvia de cada estacion de referencia de las parroquias con emergencias o con mas lluvia
    const filas = sel.map(p => res[p.id]).filter(r => r.ref).sort((a, b) => (b.emerg - a.emerg) || ((b.total || 0) - (a.total || 0))).slice(0, 18);
    document.getElementById("sub-serie").textContent = "Parroquias con emergencias o con más lluvia ese día: lluvia del día, máximo en una hora y número de emergencias.";
    grafico("g-serie", { data: { labels: filas.map(r => r.p.nombre), datasets: [
      { type: "bar", label: "Lluvia del día (mm)", data: filas.map(r => r.total), backgroundColor: filas.map(r => color(r.total || 0, CLASES_DIA)), yAxisID: "y" },
      { type: "bar", label: "Máx. en 1 hora (mm)", data: filas.map(r => r.max_h), backgroundColor: "#173f8f", yAxisID: "y" },
      { type: "line", label: "Emergencias", data: filas.map(r => r.emerg), borderColor: "#c0392b", backgroundColor: "#c0392b", showLine: false, pointRadius: 6, pointStyle: "rectRot", yAxisID: "y2" }] },
      options: { maintainAspectRatio: false, plugins: { legend: { labels: { boxWidth: 12, font: { size: 11 } } } },
        scales: { x: { ticks: { font: { size: 9 }, maxRotation: 60, minRotation: 45 } }, y: { beginAtZero: true, title: { display: true, text: "mm" } },
          y2: { position: "right", beginAtZero: true, ticks: { precision: 0 }, grid: { drawOnChartArea: false }, title: { display: true, text: "emergencias" } } } } });
  } else {
    document.getElementById("sub-serie").textContent = gran === "dia" ? "Emergencias por día (barras), lluvia promedio de las estaciones de referencia y la más intensa en una hora (líneas)."
      : `Emergencias por ${gran === "mes" ? "mes" : "año"} (barras) y días con lluvia fuerte (≥10 mm en 1 h) en las estaciones de referencia (línea).`;
    const ds = [{ type: "bar", label: "Emergencias", data: ks.map(k => grupos[k].e), backgroundColor: "#c0392b", yAxisID: "y2", order: 2 }];
    if (gran === "dia") {
      ds.push({ type: "line", label: "Lluvia promedio del día (mm)", data: ks.map(k => prom(grupos[k].lluvia)), borderColor: "#5bbfa8", backgroundColor: "#5bbfa8", pointRadius: 0, tension: .2, yAxisID: "y", order: 1 });
      ds.push({ type: "line", label: "Máx. en 1 hora (mm)", data: ks.map(k => grupos[k].maxh), borderColor: "#173f8f", backgroundColor: "#173f8f", pointRadius: 0, borderDash: [4, 3], tension: .2, yAxisID: "y", order: 1 });
    } else ds.push({ type: "line", label: "Días con lluvia fuerte", data: ks.map(k => grupos[k].fuertes), borderColor: "#173f8f", backgroundColor: "#173f8f", pointRadius: 2, tension: .2, yAxisID: "y", order: 1 });
    grafico("g-serie", { data: { labels: ks, datasets: ds }, options: { maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      plugins: { legend: { labels: { boxWidth: 12, font: { size: 11 } } } },
      scales: { x: { ticks: { font: { size: 9 }, maxTicksLimit: 14 } }, y: { beginAtZero: true, title: { display: true, text: gran === "dia" ? "mm" : "días fuertes" } },
        y2: { position: "right", beginAtZero: true, ticks: { precision: 0 }, grid: { drawOnChartArea: false }, title: { display: true, text: "emergencias" } } } } });
  }
  // ---- intensidad
  const tc = Object.fromEntries(INTENS.map(c => [c[0], [0, 0, 0]]));
  sel.forEach(p => INTENS.forEach(c => tc[c[0]] = tc[c[0]].map((x, k) => x + res[p.id].clases[c[0]][k])));
  grafico("g-intensidad", { data: { labels: INTENS.map(c => c[0]), datasets: [
    { type: "bar", label: "Días", data: INTENS.map(c => tc[c[0]][0]), backgroundColor: INTENS.map(c => c[2]), borderColor: "#7d8792", borderWidth: .5, yAxisID: "y" },
    { type: "line", label: "% días con emergencia", data: INTENS.map(c => tc[c[0]][0] ? tc[c[0]][1] / tc[c[0]][0] * 100 : null), borderColor: "#c0392b", backgroundColor: "#c0392b", yAxisID: "y2", tension: .2 }] },
    options: { maintainAspectRatio: false, plugins: { legend: { labels: { boxWidth: 12, font: { size: 11 } } },
      tooltip: { callbacks: { afterBody: it => `Emergencias: ${tc[INTENS[it[0].dataIndex][0]][2]}` } } },
      scales: { y: { type: nd > 60 ? "logarithmic" : "linear", beginAtZero: true, title: { display: true, text: nd > 60 ? "días (escala log.)" : "días" }, ticks: { font: { size: 10 } } },
        y2: { position: "right", min: 0, title: { display: true, text: "% con emergencia" }, grid: { drawOnChartArea: false } } } } });
  // ---- tabla de parroquias
  const filas = PARR.filter(p => !fB.value || reparar(p.brigada) === fB.value).map(p => res[p.id])
    .sort((a, b) => ((b[orden.col] ?? -1) - (a[orden.col] ?? -1)) || (b.emerg - a.emerg));
  const maxEm = Math.max(1, ...filas.map(r => r.emerg));
  document.getElementById("tabla-h").innerHTML = `<thead><tr><th>Parroquia</th><th>Brigada</th><th class="num" data-c="emerg">Emergencias</th>
    <th class="num" data-c="total">Lluvia ${unDia ? "del día" : "total"} (mm)</th><th class="num" data-c="max_dia">Máx. en un día</th><th class="num" data-c="max_h">Máx. en 1 h</th>
    ${unDia ? "" : '<th class="num" data-c="fuertes">Días fuertes</th>'}<th>Estación de referencia</th></tr></thead><tbody>` +
    filas.map(r => `<tr data-id="${r.p.id}" class="${r.p.id === fP.value ? "sel" : ""}"><td>${r.p.nombre}</td><td>${reparar(r.p.brigada)}</td>
      <td class="num"><span class="barrita" style="width:${r.emerg / maxEm * 50}px;background:#c0392b"></span>${r.emerg}</td>
      <td class="num"><span class="pastilla" style="background:${color(r.total ?? 0, esc)};color:${(r.total ?? 0) >= esc[1][0] ? "#fff" : "#1f3f73"}">${fmt(r.total)}</span></td>
      <td class="num">${fmt(r.max_dia)}</td><td class="num">${fmt(r.max_h)}</td>${unDia ? "" : `<td class="num">${r.fuertes}</td>`}
      <td style="color:#5d6d7e">${r.ref ? `${r.ref.e.n} (${fmt(r.ref.km)} km)` : "sin datos"}</td></tr>`).join("") + "</tbody>";
  document.querySelectorAll("#tabla-h th[data-c]").forEach(th => th.onclick = () => { orden.col = th.dataset.c; actualizarHistorico(); });
  document.querySelectorAll("#tabla-h tbody tr").forEach(tr => tr.onclick = () => { fP.value = tr.dataset.id; actualizarHistorico(); });
  // ---- lista de emergencias
  const lista = evs.slice().sort((a, b) => b.i - a.i || (b.hora > a.hora ? 1 : -1)).slice(0, 400);
  document.getElementById("titulo-lista").textContent = `Emergencias del período (${evs.length}${evs.length > 400 ? ", se muestran las 400 más recientes" : ""})`;
  document.getElementById("tabla-eventos").innerHTML = `<thead><tr><th>Fecha</th><th>Parroquia</th><th>Barrio</th><th>Causa</th><th class="num">Lluvia día</th><th class="num">Máx. 1 h</th></tr></thead><tbody>` +
    (lista.map(e => { const ll = lluviaEvento(e); const nom = (PARR.find(p => p.id === e.parroquia) || {}).nombre || e.parroquia;
      return `<tr data-la="${e.la}" data-lo="${e.lo}"><td>${e.fecha}${e.hora ? " " + e.hora : ""}</td><td>${nom}</td><td>${e.barrio}</td><td>${e.causa}</td>
        <td class="num">${ll ? fmt(ll.d) : "—"}</td><td class="num">${ll ? fmt(ll.h) : "—"}</td></tr>`; }).join("") ||
     `<tr><td colspan="6">No hay emergencias por lluvia registradas en el período y lugar elegidos.</td></tr>`) + "</tbody>";
  document.querySelectorAll("#tabla-eventos tbody tr[data-la]").forEach(tr => tr.onclick = () => mapaH.setView([+tr.dataset.la, +tr.dataset.lo], 15));
  const bs = {}; evs.forEach(e => { const k = `${e.barrio || "sin barrio"} (${(PARR.find(p => p.id === e.parroquia) || {}).nombre || e.parroquia})`; bs[k] = (bs[k] || 0) + 1; });
  const top = Object.entries(bs).sort((a, b) => b[1] - a[1]).slice(0, 10), bmax = top.length ? top[0][1] : 1;
  document.getElementById("barrios").innerHTML = top.map(([b, n]) => `<div style="font-size:12.5px"><span class="barrita" style="width:${n / bmax * 120}px;background:#c0392b"></span>${b}: <b>${n}</b></div>`).join("") || "<p class='sub'>Sin emergencias en el período.</p>";
}
const orden = { col: "emerg" };
function rango(tipo) {
  const fin = idxDe(fH.value || fechaDe(ULTIMO));
  const ini = { dia: fin, semana: fin - 6, mes: fin - 29, anio: fin - 364, todo: 0 }[tipo];
  if (tipo === "todo") fH.value = fechaDe(ULTIMO);
  fD.value = fechaDe(Math.max(0, ini)); actualizarHistorico();
}
document.querySelectorAll(".rapidos button").forEach(b => b.onclick = () => rango(b.dataset.r));
fC.addEventListener("change", () => { if (fC.value) { fD.value = fC.value; fH.value = fC.value; fB.value = ""; fP.value = ""; opcionesParroquia(); actualizarHistorico(); } });
[fD, fH, fP].forEach(s => s.addEventListener("change", actualizarHistorico));
fB.addEventListener("change", () => { fP.value = ""; opcionesParroquia(); actualizarHistorico(); });
["ver-eventos", "ver-est-h"].forEach(id => document.getElementById(id).addEventListener("change", actualizarHistorico));
document.querySelectorAll("#sel-indicador button").forEach(b => b.onclick = () => {
  document.querySelectorAll("#sel-indicador button").forEach(x => x.classList.toggle("activo", x === b));
  estado.indicador = b.dataset.i; actualizarHistorico();
});
actualizarHistorico();

// ---------------------------------------------------------------- estaciones hora por hora (ultimos 7 dias)
(function horaPorHora() {
  const ED = window.ESTACIONES_DIAS, selDia = document.getElementById("hh-dia"), selEst = document.getElementById("hh-est");
  if (!selDia) return;
  if (!ED || !ED.dias || !Object.keys(ED.dias).length) {
    document.getElementById("hh-nota").textContent = "Todavía no hay días guardados: se guardan cada día después de la 1h00."; return;
  }
  const VARS = [["lluvia", "Lluvia (mm en cada hora)", "bar", "#2f86c8"], ["temp", "Temperatura (°C)", "line", "#1f3f73"],
    ["hr", "Humedad relativa (%)", "line", "#5bbfa8"], ["viento", "Viento (km/h)", "line", "#2ca25f"],
    ["rad", "Radiación solar (W/m²)", "line", "#756bb1"], ["presion", "Presión atmosférica (hPa)", "line", "#4292c6"]];
  const vals = a => (a || []).filter(x => x !== null && x !== undefined);
  const suma = a => vals(a).length ? vals(a).reduce((s, x) => s + x, 0) : null;
  const max = a => vals(a).length ? Math.max(...vals(a)) : null;
  const min = a => vals(a).length ? Math.min(...vals(a)) : null;
  const prom = a => vals(a).length ? suma(a) / vals(a).length : null;
  const horaDe = (a, f) => { const m = f(a); return m === null ? "" : String(a.indexOf(m)).padStart(2, "0") + "h00"; };
  const dias = Object.keys(ED.dias).sort().reverse();
  selDia.innerHTML = dias.map(d => `<option value="${d}">${fechaLarga(d)}</option>`).join("");
  const est = () => ED.dias[selDia.value].estaciones;
  const graf = {};
  const ordenHH = { col: "lluvia", asc: false };

  function resumen(e) {
    const v = e.v;
    return { nombre: e.nombre, red: e.red, lluvia: suma(v.lluvia), max1h: max(v.lluvia), tmax: max(v.temp), tmin: min(v.temp),
             hr: prom(v.hr), viento: max(v.viento_max || v.viento), rad: max(v.rad), presion: prom(v.presion) };
  }
  function llenarEstaciones() {
    const antes = selEst.value, lista = est();
    selEst.innerHTML = ["CBDMQ", "EPMAPS"].map(r => `<optgroup label="${r}">` +
      lista.filter(e => e.red === r).map(e => `<option>${e.nombre}</option>`).join("") + "</optgroup>").join("");
    if (lista.some(e => e.nombre === antes)) selEst.value = antes;
  }
  function graficos() {
    const e = est().find(x => x.nombre === selEst.value); if (!e) return;
    Object.values(graf).forEach(g => g.destroy());
    const presentes = VARS.filter(x => e.v[x[0]]);
    document.getElementById("hh-graficos").innerHTML = presentes.map(x =>
      `<div class="hh-g"><b>${x[1]}</b><div class="grafico-hh"><canvas id="hh-${x[0]}"></canvas></div></div>`).join("");
    const horas = [...Array(24).keys()].map(h => String(h).padStart(2, "0") + "h");
    presentes.forEach(([k, titulo, tipo, col]) => {
      const ds = [{ type: tipo, label: k === "viento" ? "Promedio de la hora" : titulo, data: e.v[k], backgroundColor: col, borderColor: col,
                    borderWidth: tipo === "line" ? 2 : 0, pointRadius: tipo === "line" ? 1.5 : 0 }];
      if (k === "viento" && e.v.viento_max)
        ds.push({ type: "line", label: e.red === "CBDMQ" ? "Ráfaga máxima" : "Máximo de la hora", data: e.v.viento_max, borderColor: col,
                  borderDash: [4, 3], borderWidth: 1.5, pointRadius: 0 });
      graf[k] = new Chart(document.getElementById("hh-" + k), { data: { labels: horas, datasets: ds },
        options: { animation: false, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
          plugins: { legend: { display: k === "viento", labels: { boxWidth: 10, font: { size: 10 } } } },
          scales: { x: { ticks: { maxTicksLimit: 12, font: { size: 9 } } }, y: { beginAtZero: k === "lluvia", ticks: { font: { size: 9 } } } } } });
    });
    const r = resumen(e), v = e.v, partes = [];
    if (v.lluvia) partes.push(r.lluvia > 0.2 ? `lluvia total de <b>${fmt(r.lluvia)} mm</b> (la hora más intensa, ${horaDe(v.lluvia, max)}: ${fmt(r.max1h)} mm)` : "<b>sin lluvia</b>");
    if (v.temp) partes.push(`temperatura entre <b>${fmt(r.tmin)} °C</b> (${horaDe(v.temp, min)}) y <b>${fmt(r.tmax)} °C</b> (${horaDe(v.temp, max)})`);
    if (v.hr) partes.push(`humedad promedio de ${fmt(r.hr, 0)} %`);
    if (v.viento) partes.push(`viento máximo de ${fmt(r.viento, 0)} km/h (${horaDe(v.viento_max || v.viento, max)})`);
    if (v.presion) partes.push(`presión promedio de ${fmt(r.presion, 1)} hPa`);
    document.getElementById("hh-resumen").innerHTML = `<b>${e.nombre}</b>, ${fechaLarga(selDia.value)}: ${partes.join("; ")}.`;
  }
  function tabla() {
    const filas = est().map(resumen);
    const c = ordenHH.col;
    filas.sort((a, b) => c === "nombre" ? a.nombre.localeCompare(b.nombre) * (ordenHH.asc ? 1 : -1)
      : ((a[c] ?? -1e9) - (b[c] ?? -1e9)) * (ordenHH.asc ? 1 : -1));
    const COLS = [["nombre", "Estación"], ["lluvia", "Lluvia total (mm)"], ["max1h", "Máx. en 1 hora (mm)"], ["tmax", "Temp. máx. (°C)"],
      ["tmin", "Temp. mín. (°C)"], ["hr", "Humedad prom. (%)"], ["viento", "Viento máx. (km/h)"], ["rad", "Radiación máx. (W/m²)"], ["presion", "Presión prom. (hPa)"]];
    const dec = { hr: 0, viento: 0, rad: 0 };
    document.getElementById("hh-tabla").innerHTML = "<thead><tr>" + COLS.map(([k, t]) => `<th data-c="${k}">${t}${k === c ? (ordenHH.asc ? " ▲" : " ▼") : ""}</th>`).join("") +
      "</tr></thead><tbody>" + filas.map(f => `<tr data-n="${f.nombre}"${f.nombre === selEst.value ? ' class="sel"' : ""}><td>${f.nombre}</td>` +
      COLS.slice(1).map(([k]) => `<td>${fmt(f[k], dec[k] ?? 1)}</td>`).join("") + "</tr>").join("") + "</tbody>";
    document.querySelectorAll("#hh-tabla th").forEach(th => th.onclick = () => {
      ordenHH.asc = ordenHH.col === th.dataset.c ? !ordenHH.asc : th.dataset.c === "nombre";
      ordenHH.col = th.dataset.c; tabla();
    });
    document.querySelectorAll("#hh-tabla tbody tr").forEach(tr => tr.onclick = () => {
      selEst.value = tr.dataset.n; graficos(); tabla();
      document.getElementById("hh-resumen").scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }
  selDia.onchange = () => { llenarEstaciones(); graficos(); tabla(); };
  selEst.onchange = () => { graficos(); tabla(); };
  llenarEstaciones(); graficos(); tabla();
})();
