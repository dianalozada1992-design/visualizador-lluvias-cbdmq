/* Visualizador de lluvias, rios y emergencias - CBDMQ
   Datos: datos/capas.js (fijo), datos/historico.js (fijo) y datos/tiempo_real.js (se recarga cada 5 minutos). */
"use strict";

// ---------------------------------------------------------------- pestañas
document.querySelectorAll(".pestana").forEach(b => b.addEventListener("click", () => {
  if (!b.dataset.pagina) return;  // en la version web la pagina historica es otra direccion
  document.querySelectorAll(".pestana").forEach(x => x.classList.toggle("activa", x === b));
  document.querySelectorAll(".pagina").forEach(p => p.classList.toggle("activa", p.id === b.dataset.pagina));
  setTimeout(() => {
    mapa.invalidateSize(); mapaH.invalidateSize();
    if (b.dataset.pagina === "historico") {
      // el mapa y los graficos se dibujan al mostrarse la pestaña (oculta no tienen tamaño)
      if (!mapaH._encuadrado) { mapaH.fitBounds(L.geoJSON(CAPAS.brigadas).getBounds(), { padding: [6, 6] }); mapaH._encuadrado = true; }
      actualizarHistorico();
    }
  }, 80);
}));

// ---------------------------------------------------------------- iconos del tiempo (SVG)
function iconoSVG(tipo, noche) {
  const sol = noche ? '<circle cx="15" cy="13" r="8" fill="#f2c230"/><circle cx="19" cy="10" r="7" fill="#f7f9fc"/>'
    : '<g stroke="#f2c230" stroke-width="2.2" stroke-linecap="round"><line x1="15" y1="1" x2="15" y2="5"/><line x1="15" y1="21" x2="15" y2="25"/><line x1="3" y1="13" x2="7" y2="13"/><line x1="23" y1="13" x2="27" y2="13"/><line x1="6.5" y1="4.5" x2="9" y2="7"/><line x1="21" y1="19" x2="23.5" y2="21.5"/><line x1="6.5" y1="21.5" x2="9" y2="19"/><line x1="21" y1="7" x2="23.5" y2="4.5"/></g><circle cx="15" cy="13" r="6.5" fill="#f2c230"/>';
  const nube = (x, y, s, c) => `<g transform="translate(${x},${y}) scale(${s})"><path d="M8 22 h22 a7 7 0 0 0 0-14 a9 9 0 0 0-17-2 a7 7 0 0 0-5 16z" fill="${c}" stroke="#7d8792" stroke-width="1.3"/></g>`;
  const gotas = (n, y) => Array.from({ length: n }, (_, i) => `<ellipse cx="${22 + (i - (n - 1) / 2) * 7}" cy="${y}" rx="2" ry="3" fill="#2b78c2"/>`).join("");
  const lineas = n => Array.from({ length: n }, (_, i) => `<line x1="${17 + i * 6}" y1="34" x2="${14 + i * 6}" y2="41" stroke="#2b78c2" stroke-width="2"/>`).join("");
  const rayo = '<polygon points="30,30 25,38 29,38 26,45 35,35 31,35 34,30" fill="#f2c230" stroke="#8c6d00" stroke-width=".6"/>';
  const v = { despejado: noche ? '<g transform="translate(7,6)">' + sol + "</g>" : '<g transform="translate(7,6)">' + sol + "</g>",
    parcial: sol + nube(8, 10, 0.95, "#dfe3e8"), nublado: nube(14, 2, .75, "#9ea7b1") + nube(4, 10, .95, "#dfe3e8"),
    aislada: sol + nube(8, 8, .95, "#dfe3e8") + gotas(2, 38), lluvia: nube(5, 4, 1, "#dfe3e8") + gotas(3, 37),
    chubasco: nube(5, 4, 1, "#9ea7b1") + lineas(4), tormenta: nube(5, 4, 1, "#9ea7b1") + lineas(2) + rayo };
  return `<svg viewBox="0 0 46 46">${v[tipo] || v.parcial}</svg>`;
}

// ---------------------------------------------------------------- mapa base
const mapa = mapaBase("mapa");

const capaBrigadas = L.geoJSON(CAPAS.brigadas, { style: { color: "#1f3f73", weight: 2.2, fill: false }, interactive: false,
  onEachFeature: (f, l) => l.bindTooltip(reparar(f.properties.nombre), { permanent: false }) }).addTo(mapa);
const RIOS_PRINCIPALES = ["Machángara", "Monjas", "San Pedro", "Guayllabamba", "Pita", "Pisque", "Cinto", "Grande", "Chiche", "Guambi", "Coyago", "Blanco"];
const capaRios = L.layerGroup().addTo(mapa);
const rotulados = new Set();
CAPAS.rios.features.forEach(f => {
  const coords = f.geometry.coordinates.map(c => [c[1], c[0]]);
  const linea = L.polyline(coords, { color: "#4a90d9", weight: 1.8, opacity: .85 }).bindTooltip(f.properties.nombre, { sticky: true });
  capaRios.addLayer(linea);
  const nom = f.properties.nombre;
  if (RIOS_PRINCIPALES.some(r => nom.includes(r)) && !rotulados.has(nom) && coords.length > 6) {
    rotulados.add(nom);
    capaRios.addLayer(L.marker(coords[Math.floor(coords.length / 2)], { opacity: 0, interactive: false })
      .bindTooltip(nom, { permanent: true, direction: "center", className: "etiqueta-rio" }));
  }
});
let capaPronostico = L.geoJSON(null).addTo(mapa);
const capaEstaciones = L.layerGroup().addTo(mapa);
const capaCaudal = L.layerGroup().addTo(mapa);

// ---------------------------------------------------------------- pronostico
// variables del mapa de pronostico: lluvia (verde a azul), temperatura (azules) e indice UV (morados, categorias OMS)
const VARIABLES_PRON = {
  lluvia: { titulo: "Lluvia pronosticada en el día", clases: CLASES_DIA },
  tmax: { titulo: "Temperatura máxima del día", i: 0, clases: [[12, "#deebf7", "Menos de 12 °C"], [16, "#9ecae1", "12 a 16 °C"],
    [20, "#4292c6", "16 a 20 °C"], [24, "#2171b5", "20 a 24 °C"], [Infinity, "#08306b", "24 °C o más"]] },
  tmin: { titulo: "Temperatura mínima del día", i: 1, clases: [[4, "#deebf7", "Menos de 4 °C"], [7, "#9ecae1", "4 a 7 °C"],
    [10, "#4292c6", "7 a 10 °C"], [13, "#2171b5", "10 a 13 °C"], [Infinity, "#08306b", "13 °C o más"]] },
  uv: { titulo: "Índice UV máximo (OMS)", i: 2, clases: [[3, "#ece7f2", "Bajo (0–2)"], [6, "#bcbddc", "Moderado (3–5)"],
    [8, "#9e9ac8", "Alto (6–7)"], [11, "#756bb1", "Muy alto (8–10)"], [Infinity, "#54278f", "Extremo (11+)"]] },
};
estado.variable = "lluvia";
function climaDe(id) { return ((TR && TR.clima && TR.clima.por_parroquia) || {})[id] || {}; }
function valorPron(pr, id, dia) {
  const v = VARIABLES_PRON[estado.variable];
  if (estado.variable === "lluvia") return (pr.por_parroquia[id] || {})[dia] || 0;
  const c = climaDe(id)[dia]; return c ? c[v.i] : null;
}
function dibujarPronostico() {
  mapa.removeLayer(capaPronostico);
  const pr = TR && TR.pronostico;
  if (!pr || !estado.dia) { capaPronostico = L.geoJSON(null).addTo(mapa); return; }
  const v = VARIABLES_PRON[estado.variable];
  capaPronostico = L.geoJSON(CAPAS.parroquias, {
    style: f => { const x = valorPron(pr, f.properties.id, estado.dia);
      return { fillColor: x == null ? "#ffffff" : color(x, v.clases), fillOpacity: x == null ? .3 : .72, color: "#fff", weight: .8 }; },
    onEachFeature: (f, l) => {
      const p = f.properties, val = pr.por_parroquia[p.id] || {}, cl = climaDe(p.id);
      l.bindPopup(`<h3>${p.nombre}</h3><div>Brigada distrital: <b>${reparar(p.brigada)}</b></div>` +
        `<table class="tabla-popup"><thead><tr><th>Día</th><th>Lluvia</th><th>Temp. máx / mín</th><th>Índice UV</th><th>Radiación</th></tr></thead><tbody>` +
        pr.dias.map(d => { const c = cl[d]; return `<tr><td>${etiquetaDia(d).split(",")[0]}</td><td><b>${fmt(val[d])} mm</b></td>` +
          (c ? `<td>${fmt(c[0], 0)} / ${fmt(c[1], 0)} °C</td><td>${fmt(c[2], 0)} (${categoriaUV(c[2])})</td><td>${fmt(c[3], 0)} MJ/m²</td>` : "<td colspan=3>sin dato todavía</td>") + "</tr>"; }).join("") +
        "</tbody></table>", { maxWidth: 460, minWidth: 380 });
      const ch = cl[estado.dia];
      l.bindTooltip(`${p.nombre}: ${fmt(val[estado.dia])} mm` + (ch ? ` · ${fmt(ch[0], 0)}/${fmt(ch[1], 0)} °C · UV ${fmt(ch[2], 0)}` : ""), { sticky: true });
    } }).addTo(mapa);
  capaPronostico.bringToBack();
  leyenda("leyenda-pronostico", v.titulo, v.clases);
  if (estado.variable !== "lluvia" && !(TR.clima && TR.clima.por_parroquia))
    document.getElementById("leyenda-pronostico").insertAdjacentHTML("beforeend", "<span class='caja'>Temperatura y UV aún no disponibles; se calculan cada 3 horas.</span>");
}
document.querySelectorAll("#sel-var button").forEach(b => b.onclick = () => {
  estado.variable = b.dataset.v;
  document.querySelectorAll("#sel-var button").forEach(x => x.classList.toggle("activo", x === b));
  dibujarPronostico();
});
function etiquetaDia(d) {
  const hoy = new Date(); hoy.setHours(0, 0, 0, 0);
  const f = new Date(d + "T00:00:00"); const dif = Math.round((f - hoy) / 864e5);
  const nombre = ["Hoy", "Mañana", "Pasado mañana"][dif] || "";
  return `${nombre ? nombre + ", " : ""}${DIAS_SEM[f.getDay()]} ${f.getDate()}`;
}
function selectorDias() {
  const cont = document.getElementById("sel-dia");
  const dias = (TR && TR.pronostico && TR.pronostico.dias) || [];
  if (!estado.dia || !dias.includes(estado.dia)) estado.dia = dias[0] || null;
  cont.innerHTML = dias.map(d => `<button data-d="${d}" class="${d === estado.dia ? "activo" : ""}">${etiquetaDia(d).split(",")[0]}</button>`).join("") +
    `<button data-d="" class="${estado.dia ? "" : "activo"}">Ninguno</button>`;
  cont.querySelectorAll("button").forEach(b => b.onclick = () => { estado.dia = b.dataset.d || null; selectorDias(); dibujarPronostico(); dibujarBrigadas(); });
}
// indice UV por categorias de la OMS
function categoriaUV(uv) { return uv == null ? "" : uv < 3 ? "bajo" : uv < 6 ? "moderado" : uv < 8 ? "alto" : uv < 11 ? "muy alto" : "extremo"; }
function climaBrigada(b, dia) {
  const vals = CAPAS.parroquias.features.filter(f => reparar(f.properties.brigada) === reparar(b)).map(f => climaDe(f.properties.id)[dia]).filter(Boolean);
  if (!vals.length) return "";
  const tmax = Math.max(...vals.map(v => v[0])), tmin = Math.min(...vals.map(v => v[1])), uv = Math.max(...vals.map(v => v[2]));
  return `<div class="brig-clima">🌡️ ${fmt(tmin, 0)} a ${fmt(tmax, 0)} °C · ☀️ UV ${fmt(uv, 0)} (${categoriaUV(uv)})</div>`;
}
function dibujarBrigadas() {
  const pr = TR && TR.pronostico, cont = document.getElementById("brigadas");
  const dia = estado.dia || (pr && pr.dias[0]);
  if (!pr || !dia) { cont.innerHTML = "<p class='sub'>Sin pronóstico disponible.</p>"; return; }
  document.getElementById("titulo-brigadas").textContent = `Pronóstico por brigada distrital · ${etiquetaDia(dia)}`;
  const orden = ["Calderón", "La Delicia", "Eugenio Espejo", "Tumbaco", "Manuela Sáenz", "Eloy Alfaro", "Quitumbe", "Los Chillos"];
  const nombres = Object.keys(pr.brigadas).sort((a, b) => orden.indexOf(reparar(a)) - orden.indexOf(reparar(b)));
  cont.innerHTML = nombres.map(b => {
    const d = pr.brigadas[b].dias[dia]; if (!d) return "";
    return `<div class="brig"><div class="brig-cab"><b>${reparar(b)}</b><span class="brig-mm" style="background:${color(d.media_mm, CLASES_DIA)};color:${d.media_mm >= 5 ? "#fff" : "#1f3f73"}">${fmt(d.media_mm, 0)} mm</span></div>
      <div class="periodos">${d.periodos.map(p => `<div>${p.periodo}${iconoSVG(p.icono, p.noche)}<b>${fmt(p.mm)} mm</b></div>`).join("")}</div>
      <div class="brig-top">Más lluvia en: ${d.mas_lluvia.map(x => `${x[0]} (${fmt(x[1], 0)} mm)`).join(", ")}</div>${climaBrigada(b, dia)}</div>`;
  }).join("");
  const iq = TR.clima && TR.clima.inamhi_quito;
  document.getElementById("nota-pronostico").textContent = `Lluvia: modelos ${pr.modelos.join(", ")}, corregidos con las estaciones del DMQ. ` +
    "Temperatura, índice UV y radiación: modelos verificados con las estaciones CBDMQ (error medio de 1,3 °C en la máxima y 1,6 °C en la mínima), " +
    "en el centro poblado de cada parroquia. " + (iq ? `Referencia oficial INAMHI para Quito (${iq.fecha}): ${fmt(iq.temp_min, 1)} a ${fmt(iq.temp_max, 1)} °C, índice UV ${iq.uv}. ` : "") +
    "Los aguaceros de Quito son muy localizados: confirme siempre con las estaciones en tiempo real.";
}

// ---------------------------------------------------------------- estaciones con lluvia
function estacionesTodas() { return TR ? [...(TR.cbdmq || []), ...(TR.lluvia_epmaps || [])].filter(e => e.lat) : []; }
function popupEstacion(e) {
  const id = "g" + Math.random().toString(36).slice(2);
  const html = `<h3>${e.red === "CBDMQ" ? "CBDMQ " + e.nombre : e.codigo + " " + e.nombre}</h3>
    <div>${e.red} · ${e.tipo}</div>` + (e.sin_datos ? "<div><i>Sin datos recientes</i></div>" :
    `<div>Última hora: <b>${fmt(e.lluvia_1h)} mm</b> · 3 h: <b>${fmt(e.lluvia_3h)} mm</b></div>
     <div>Hoy: <b>${fmt(e.lluvia_hoy)} mm</b> · 24 h: <b>${fmt(e.lluvia_24h)} mm</b></div>
     <div class="sub">Último dato: ${e.ultimo_dato}${e.retraso_min > 90 ? " (con retraso)" : ""}${e.dato_anterior ? " · la última consulta falló, se muestra el dato anterior" : ""}</div>
     <div class="popup-grafico"><canvas id="${id}"></canvas></div>`);
  return { html, id };
}
function graficoPopup(id, serie, tipo, etiqueta, umbral) {
  setTimeout(() => {
    const c = document.getElementById(id); if (!c || !serie) return;
    const conj = [{ type: tipo, label: etiqueta, data: serie.map(x => x[1]), backgroundColor: "#2f86c8", borderColor: "#1f3f73", pointRadius: 0, borderWidth: tipo === "line" ? 2 : 0 }];
    if (umbral) conj.push({ type: "line", label: "Umbral de crecida", data: serie.map(() => umbral), borderColor: "#173f8f", borderDash: [5, 4], pointRadius: 0, borderWidth: 1.5 });
    new Chart(c, { data: { labels: serie.map(x => x[0].slice(11, 16)), datasets: conj },
      options: { animation: false, maintainAspectRatio: false, plugins: { legend: { display: !!umbral, labels: { boxWidth: 10, font: { size: 10 } } } },
        scales: { x: { ticks: { maxTicksLimit: 6, font: { size: 9 } } }, y: { beginAtZero: tipo === "bar", ticks: { font: { size: 9 } } } } } });
  }, 60);
}
function dibujarEstaciones() {
  capaEstaciones.clearLayers();
  const v = estado.ventana, clases = CLASES_AHORA[v];
  estacionesTodas().forEach(e => {
    const val = e.sin_datos ? null : e[v];
    const radio = e.red === "CBDMQ" ? 9 : 7;
    const m = L.circleMarker([e.lat, e.lon], { radius: val > 0 ? radio + Math.min(val, 20) / 3 : radio,
      fillColor: val === null ? "#ffffff" : color(val, clases), fillOpacity: .95, color: e.red === "CBDMQ" ? "#7d3c98" : "#1f3f73",
      weight: e.red === "CBDMQ" ? 2.5 : 1.2, dashArray: val === null ? "2 2" : null });
    m.on("click", () => { const p = popupEstacion(e); m.bindPopup(p.html).openPopup(); graficoPopup(p.id, e.horaria, "bar", "Lluvia por hora (mm)"); });
    m.bindTooltip(`${e.red === "CBDMQ" ? "CBDMQ " : ""}${e.nombre}: ${val === null ? "sin datos" : fmt(val) + " mm"}`);
    e._marcador = m;
    capaEstaciones.addLayer(m);
  });
  leyenda("leyenda-estaciones", `Lluvia medida ${NOMBRE_VENTANA[v]} (mm)`, clases, true);
  document.getElementById("leyenda-estaciones").insertAdjacentHTML("beforeend",
    '<span class="caja"><i class="circulo" style="border:2.5px solid #7d3c98"></i>CBDMQ</span><span class="caja"><i class="circulo" style="border:1.5px solid #1f3f73"></i>EPMAPS</span><span class="caja"><i class="circulo" style="border:1px dashed #1f3f73;background:#fff"></i>Sin datos</span>');
  const lista = estacionesTodas().filter(e => !e.sin_datos && e[v] > 0).sort((a, b) => b[v] - a[v]);
  document.getElementById("sub-lloviendo").textContent = lista.length ? `${lista.length} estaciones registraron lluvia ${NOMBRE_VENTANA[v]}.` : `Ninguna estación registró lluvia ${NOMBRE_VENTANA[v]}.`;
  const cont = document.getElementById("lista-lluvia");
  cont.innerHTML = lista.slice(0, 25).map((e, i) => `<div class="fila" data-i="${i}"><span class="punto" style="background:${color(e[v], clases)}"></span>
      <span>${e.red === "CBDMQ" ? "CBDMQ " + e.nombre : e.nombre}<small>${e.red} · último dato ${e.ultimo_dato.slice(11)}</small></span><span class="mm">${fmt(e[v])} mm</span></div>`).join("");
  cont.querySelectorAll(".fila").forEach(f => f.onclick = () => { const e = lista[+f.dataset.i]; mapa.setView([e.lat, e.lon], 13); e._marcador.fire("click"); });
}

// ---------------------------------------------------------------- caudales
function dibujarCaudal() {
  capaCaudal.clearLayers();
  const rios = (TR && TR.rios) || [];
  const clase = r => r.estado.startsWith("Muy") ? "alto" : r.estado === "Creciendo" ? "creciendo" : r.estado === "Bajando" ? "bajando" : "estable";
  const flecha = r => ({ alto: "▲▲", creciendo: "▲", bajando: "▼", estable: "▶" })[clase(r)];
  const porEst = {};
  rios.forEach(r => { (porEst[r.codigo] = porEst[r.codigo] || []).push(r); });
  Object.values(porEst).forEach(lst => {
    const r0 = lst.find(x => x.variable.startsWith("Caudal")) || lst[0];
    const icono = L.divIcon({ className: "", html: `<div style="background:#fff;border:2px solid #1f3f73;border-radius:6px;padding:1px 4px;font-size:12px;font-weight:800" class="${clase(r0)}">${flecha(r0)}</div>`, iconSize: [26, 20] });
    const m = L.marker([r0.lat, r0.lon], { icon: icono });
    m.on("click", () => {
      const id = "g" + Math.random().toString(36).slice(2);
      m.bindPopup(`<h3>${r0.codigo} ${r0.nombre}</h3>` + lst.map(r => `<div>${r.variable}: <b>${fmt(r.actual, 3)} ${r.unidad}</b> (${r.cambio_6h_pct > 0 ? "+" : ""}${fmt(r.cambio_6h_pct)} % en 6 h) · <b>${r.estado}</b></div>`).join("") +
        `<div class="sub">Último dato: ${r0.ultimo_dato}</div><div class="popup-grafico"><canvas id="${id}"></canvas></div>`).openPopup();
      graficoPopup(id, r0.serie, "line", `${r0.variable} (${r0.unidad})`, r0.umbral);
    });
    m.bindTooltip(`${r0.nombre}: ${r0.estado}`);
    r0._marcador = m;
    capaCaudal.addLayer(m);
  });
  const lista = Object.values(porEst).map(l => l.find(x => x.variable.startsWith("Caudal")) || l[0]).sort((a, b) => b.cambio_6h_pct - a.cambio_6h_pct);
  const cont = document.getElementById("lista-rios");
  cont.innerHTML = lista.length ? lista.map((r, i) => `<div class="fila" data-i="${i}"><span class="flecha ${clase(r)}">${flecha(r)}</span>
      <span>${r.nombre}<small>${r.variable} ${fmt(r.actual, 3)} ${r.unidad} · ${r.ultimo_dato.slice(5)}</small></span>
      <span class="mm">${r.cambio_6h_pct > 0 ? "+" : ""}${fmt(r.cambio_6h_pct)} %</span></div>`).join("") : "<p class='sub'>Sin datos de telemetría.</p>";
  cont.querySelectorAll(".fila").forEach(f => f.onclick = () => { const r = lista[+f.dataset.i]; mapa.setView([r.lat, r.lon], 12); r._marcador.fire("click"); });
  return lista;
}

// ---------------------------------------------------------------- cifras de la pagina 1
// ---------------------------------------------------------------- alertas (las mismas que se envian por Telegram)
function dibujarAlertas() {
  const A = TR.alertas, cont = document.getElementById("lista-alertas"), sub = document.getElementById("sub-alertas");
  if (!A) { sub.textContent = "Sin información de alertas."; cont.innerHTML = ""; return; }
  const orden = { alerta: 0, crecida: 1, condiciones: 2, aviso: 3, cuenca: 4, control: 5 };
  const act = [...A.activas].sort((a, b) => orden[a.tipo] - orden[b.tipo] || b.nivel - a.nivel || (b.mm_1h || 0) - (a.mm_1h || 0));
  const env = A.enviadas && A.enviadas.length ? `Último envío por Telegram: ${A.hora.slice(11)} a ${A.enviadas.join(", ")}.` : "";
  sub.innerHTML = (act.length ? `${act.length} situaciones activas (revisado ${A.hora.slice(11)}). ` : `Sin alertas (revisado ${A.hora.slice(11)}). `) + env +
    (A.error_envio ? ` <b>No se pudo enviar a ${A.error_envio.split(":")[0]}.</b>` : "");
  const icono = { alerta: "🔵", crecida: "🌊", condiciones: "🌥️", aviso: "🟢", cuenca: "💧", control: "⚠️" };
  const titulo = a => a.tipo === "alerta" ? ["", "Lluvia fuerte", "Lluvia muy fuerte", "Lluvia muy intensa"][a.nivel] + ` (nivel ${a.nivel})` : a.tipo === "crecida" ? (a.nivel_nombre || "Río creciendo") :
    a.tipo === "cuenca" ? `Lluvia acumulada en la cuenca (${(a.nivel_nombre || "").toLowerCase()}; informativo)` :
    a.tipo === "control" ? "Dato descartado por control de calidad" :
    a.tipo === "condiciones" ? (a.nivel === 2 ? "Puede llover en 2 horas (muy probable)" : "Puede llover en 2 horas (posible, no se envía)") : "Está lloviendo";
  cont.innerHTML = act.map(a => `<div class="fila alerta-${a.tipo}"><span>${icono[a.tipo]}</span><span><b>${titulo(a)}</b><small>${a.texto}` +
    (a.detalle ? `<br><i class="detalle">${a.detalle}</i>` : "") + `</small></span><span></span></div>`).join("");
}

function cifrasMonitoreo(lluviaRios) {
  const v = estado.ventana, est = estacionesTodas().filter(e => !e.sin_datos);
  const llueve = est.filter(e => e.lluvia_1h > 0);
  const max1 = est.reduce((a, e) => (e.lluvia_1h || 0) > (a ? a.lluvia_1h : -1) ? e : a, null);
  const maxHoy = est.reduce((a, e) => (e.lluvia_hoy || 0) > (a ? a.lluvia_hoy : -1) ? e : a, null);
  const crec = (lluviaRios || []).filter(r => r.estado !== "Estable" && r.estado !== "Bajando");
  const pr = TR.pronostico; let maxP = null;
  if (pr) { const d = pr.dias[1] || pr.dias[0]; Object.entries(pr.por_parroquia).forEach(([p, val]) => { if (!maxP || val[d] > maxP[1]) maxP = [p, val[d], d]; }); }
  const nombreP = id => { const f = CAPAS.parroquias.features.find(x => x.properties.id === id); return f ? f.properties.nombre : id; };
  document.getElementById("cifras-monitoreo").innerHTML = [
    [llueve.length, "estaciones con lluvia en la última hora", `de ${est.length} con datos recientes`],
    [max1 ? fmt(max1.lluvia_1h) + " mm" : "—", "lluvia más intensa en la última hora", max1 ? (max1.red === "CBDMQ" ? "CBDMQ " : "") + max1.nombre : ""],
    [maxHoy ? fmt(maxHoy.lluvia_hoy) + " mm" : "—", "mayor acumulado de hoy", maxHoy ? (maxHoy.red === "CBDMQ" ? "CBDMQ " : "") + maxHoy.nombre : ""],
    [crec.length, "estaciones de ríos creciendo", crec.map(r => r.nombre).join(", ") || "todas estables o bajando"],
    [maxP ? fmt(maxP[1]) + " mm" : "—", "mayor lluvia pronosticada para " + (maxP ? etiquetaDia(maxP[2]).split(",")[0].toLowerCase() : ""), maxP ? nombreP(maxP[0]) : ""],
  ].map(c => `<div class="cifra"><div class="valor">${c[0]}</div><div class="rotulo">${c[1]}</div><div class="detalle">${c[2]}</div></div>`).join("");
}

// ---------------------------------------------------------------- carga de datos en vivo
function cargarTiempoReal() {
  const s = document.createElement("script");
  s.src = (window.URL_TIEMPO_REAL || "datos/tiempo_real.js") + "?t=" + Date.now();
  s.onload = () => {
    TR = window.TIEMPO_REAL; s.remove();
    const b = TR.boletin_hoy || {};
    document.getElementById("actualizado").innerHTML = "Datos actualizados: " + TR.actualizado + (TR.fuentes_anteriores ? " (algunas fuentes con datos anteriores)" : "") +
      "<br>" + (b.generado ? `Boletín de pronóstico de hoy: generado a las ${b.hora} ✔` : "<b style='color:#ffd7d7'>Boletín de pronóstico de hoy: AÚN NO GENERADO</b>");
    selectorDias(); dibujarPronostico(); dibujarEstaciones(); const r = dibujarCaudal(); dibujarBrigadas(); cifrasMonitoreo(r); dibujarAlertas();
  };
  s.onerror = () => { document.getElementById("actualizado").textContent = "No se encontraron datos en vivo (corra actualizar.py)"; s.remove(); };
  document.body.appendChild(s);
}
document.querySelectorAll("#sel-ventana button").forEach(b => b.onclick = () => {
  document.querySelectorAll("#sel-ventana button").forEach(x => x.classList.toggle("activo", x === b));
  estado.ventana = b.dataset.v; dibujarEstaciones();
});
const alternar = (id, capa, m = mapa) => document.getElementById(id).addEventListener("change", e => e.target.checked ? capa.addTo(m) : m.removeLayer(capa));
alternar("ver-estaciones", capaEstaciones); alternar("ver-rios", capaRios); alternar("ver-caudal", capaCaudal); alternar("ver-brigadas", capaBrigadas);
mapa.on("zoomend", () => document.querySelectorAll(".etiqueta-rio").forEach(e => e.style.display = mapa.getZoom() >= 10 ? "" : "none"));
cargarTiempoReal();
setInterval(cargarTiempoReal, 5 * 60 * 1000);

