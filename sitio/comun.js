/* Partes comunes de las dos paginas del visualizador (escalas de color, formatos, mapa base, leyendas). */
"use strict";
// ---------------------------------------------------------------- escalas (verde a azul)
const CLASES_DIA = [[1, "#e3f4e6", "Menos de 1 mm"], [5, "#a8dcae", "1 a 5 mm"], [10, "#5bbfa8", "5 a 10 mm"],
                    [20, "#2f86c8", "10 a 20 mm"], [Infinity, "#173f8f", "Más de 20 mm"]];
const CLASES_AHORA = { lluvia_1h: [[0.2, "#e3f4e6", "Sin lluvia"], [2, "#a8dcae", "0,2 a 2"], [5, "#5bbfa8", "2 a 5"], [10, "#2f86c8", "5 a 10"], [Infinity, "#173f8f", "10 o más"]],
  lluvia_3h: [[0.2, "#e3f4e6", "Sin lluvia"], [3, "#a8dcae", "0,2 a 3"], [8, "#5bbfa8", "3 a 8"], [15, "#2f86c8", "8 a 15"], [Infinity, "#173f8f", "15 o más"]],
  lluvia_hoy: [[0.2, "#e3f4e6", "Sin lluvia"], [5, "#a8dcae", "0,2 a 5"], [10, "#5bbfa8", "5 a 10"], [20, "#2f86c8", "10 a 20"], [Infinity, "#173f8f", "20 o más"]],
  lluvia_24h: [[0.2, "#e3f4e6", "Sin lluvia"], [5, "#a8dcae", "0,2 a 5"], [10, "#5bbfa8", "5 a 10"], [20, "#2f86c8", "10 a 20"], [Infinity, "#173f8f", "20 o más"]] };
const NOMBRE_VENTANA = { lluvia_1h: "en la última hora", lluvia_3h: "en las últimas 3 horas", lluvia_hoy: "hoy", lluvia_24h: "en 24 horas" };
const DIAS_SEM = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"];
const color = (v, clases) => (clases.find(c => v < c[0]) || clases[clases.length - 1])[1];
const fmt = (v, d = 1) => (v === null || v === undefined || isNaN(v)) ? "—" : Number(v).toLocaleString("es-EC", { minimumFractionDigits: d, maximumFractionDigits: d });
const reparar = s => (s || "").replace("Calder�n", "Calderón").replace("Manuela S�enz", "Manuela Sáenz");

const estado = { dia: null, ventana: "lluvia_1h", indicador: "emergencias" };
let TR = null;

// ---------------------------------------------------------------- mapa base
const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/";
const tesela = (ruta, op = {}) => L.tileLayer(ESRI + ruta + "/MapServer/tile/{z}/{y}/{x}", { maxZoom: 19, maxNativeZoom: 19, ...op });
// lectura y escritura del navegador que pueden fallar (ventana privada): la pagina funciona igual sin ellas
const recordar = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } };

function mapaBase(id) {
  const m = L.map(id, { zoomControl: true, minZoom: 9, maxZoom: 19 }).setView([-0.2, -78.5], 10);
  // panel "relleno": parroquias coloreadas; se aclaran al acercarse para que se vean las quebradas y calles debajo
  m.createPane("relleno").style.zIndex = 390;
  // panel "nombres": calles y sectores del mapa base, encima de los colores (no recibe clics)
  const pn = m.createPane("nombres"); pn.style.zIndex = 450; pn.style.pointerEvents = "none";
  const bases = {
    "Satélite": L.layerGroup([tesela("World_Imagery", { attribution: "Imágenes: Esri, Maxar, Earthstar Geographics" }),
      tesela("Reference/World_Transportation", { pane: "nombres", opacity: .7 }),
      tesela("Reference/World_Boundaries_and_Places", { pane: "nombres" })]),
    "Relieve": tesela("World_Topo_Map", { maxNativeZoom: 18, attribution: "Esri, HERE, Garmin, &copy; OpenStreetMap" }),
    "Calles y quebradas (OpenStreetMap)": L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",
      { maxZoom: 19, attribution: "&copy; colaboradores de OpenStreetMap" }),
    "Gris (simple)": L.layerGroup([tesela("Canvas/World_Light_Gray_Base", { maxNativeZoom: 16, attribution: "Esri, HERE, Garmin, &copy; OpenStreetMap" }),
      tesela("Canvas/World_Light_Gray_Reference", { maxNativeZoom: 16, pane: "nombres", opacity: .8 })]),
  };
  const elegida = bases[recordar("mapa_base")] ? recordar("mapa_base") : "Satélite";
  bases[elegida].addTo(m);
  L.control.layers(bases, null, { position: "topright" }).addTo(m);
  m.on("baselayerchange", e => recordar("mapa_base", e.name));
  const aclarar = () => { const z = m.getZoom(); m.getPane("relleno").style.opacity = z >= 15 ? .3 : z >= 13 ? .55 : 1; };
  m.on("zoomend", aclarar); aclarar();
  m.fitBounds(L.geoJSON(CAPAS.brigadas).getBounds(), { padding: [6, 6] });
  buscador(m);
  return m;
}

// ---------------------------------------------------------------- buscador del mapa
// Mientras se escribe: parroquias, brigadas, rios, quebradas y estaciones del visualizador.
// Con Enter o la lupa: tambien calles, barrios y lugares de OpenStreetMap (Nominatim), solo dentro del DMQ.
// (Nominatim no permite consultar letra por letra; por eso las calles se buscan solo al presionar Enter.)
const sinTildes = s => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

function lugaresPropios(m) {
  if (m._lugares) return m._lugares;
  const L0 = [];
  const poligonos = (fc, tipo) => (fc ? fc.features : []).forEach(f => L0.push({ nombre: reparar(f.properties.nombre), tipo, capa: () => L.geoJSON(f) }));
  poligonos(CAPAS.parroquias, "Parroquia");
  poligonos(CAPAS.brigadas, "Brigada");
  // un rio o quebrada puede venir en varios tramos con el mismo nombre: se juntan
  const tramos = {};
  (CAPAS.rios ? CAPAS.rios.features : []).forEach(f => { const n = f.properties.nombre; if (n) (tramos[n] = tramos[n] || []).push(f); });
  Object.entries(tramos).forEach(([n, fs]) => L0.push({ nombre: n, tipo: /quebrada/i.test(n) ? "Quebrada" : "Río", linea: true,
    capa: () => L.geoJSON({ type: "FeatureCollection", features: fs }) }));
  L0.forEach(x => { x.clave = sinTildes(x.nombre); });
  return (m._lugares = L0);
}

function buscador(m) {
  const C = L.Control.extend({ options: { position: "topleft" }, onAdd: () => {
    const d = L.DomUtil.create("div", "buscador");
    d.innerHTML = `<div class="buscador-fila"><input type="search" placeholder="Buscar calle, barrio, quebrada…" aria-label="Buscar en el mapa">` +
      `<button type="button" title="Buscar">🔍</button></div><div class="buscador-res" hidden></div>`;
    L.DomEvent.disableClickPropagation(d); L.DomEvent.disableScrollPropagation(d);
    return d;
  } });
  const caja = new C().addTo(m).getContainer();
  const inp = caja.querySelector("input"), res = caja.querySelector(".buscador-res");
  let marca = null;

  const ir = r => {
    if (marca) m.removeLayer(marca);
    if (r.capa) {
      const c = r.capa();
      marca = L.geoJSON(c.toGeoJSON(), { interactive: false, style: r.linea ? { color: "#ffd400", weight: 6, opacity: .9 } : { color: "#ffd400", weight: 4, fill: false } }).addTo(m);
      m.fitBounds(c.getBounds(), { maxZoom: 17, padding: [20, 20] });
    } else if (r.caja) {
      m.fitBounds(r.caja, { maxZoom: 18 });
      marca = L.circleMarker(r.punto, { radius: 12, color: "#ffd400", weight: 4, fill: false, interactive: false }).addTo(m);
    } else {
      m.setView(r.punto, 17);
      marca = L.circleMarker(r.punto, { radius: 12, color: "#ffd400", weight: 4, fill: false, interactive: false }).addTo(m);
    }
    setTimeout(() => { if (marca) { m.removeLayer(marca); marca = null; } }, 15000);
    res.hidden = true;
  };
  const mostrar = (lista, nota) => {
    res.replaceChildren();
    lista.forEach(r => {
      const b = document.createElement("button");
      b.type = "button";
      const t = document.createElement("small"); t.textContent = r.tipo;
      b.append(r.nombre, " ", t);
      b.addEventListener("click", () => ir(r));
      res.append(b);
    });
    if (nota) { const p = document.createElement("p"); p.textContent = nota; res.append(p); }
    res.hidden = !lista.length && !nota;
  };
  const propios = q => {
    const k = sinTildes(q.trim());
    if (k.length < 2) return [];
    const extra = typeof m.lugaresExtra === "function" ? m.lugaresExtra() : [];
    return lugaresPropios(m).concat(extra.map(x => ({ ...x, clave: sinTildes(x.nombre) })))
      .filter(x => x.clave.includes(k)).sort((a, b) => a.clave.indexOf(k) - b.clave.indexOf(k)).slice(0, 8);
  };
  inp.addEventListener("input", () => {
    const p = propios(inp.value);
    mostrar(p, inp.value.trim().length >= 3 ? "Presione Enter para buscar también calles y lugares." : null);
  });
  const buscarCalles = async () => {
    const q = inp.value.trim();
    if (q.length < 3) return;
    const p = propios(q);
    mostrar(p, "Buscando calles y lugares…");
    const zona = L.geoJSON(CAPAS.brigadas).getBounds().pad(.05).toBBoxString();
    try {
      const url = "https://nominatim.openstreetmap.org/search?format=jsonv2&limit=8&countrycodes=ec&accept-language=es&bounded=1" +
        "&viewbox=" + zona + "&q=" + encodeURIComponent(q);
      const j = await (await fetch(url)).json();
      const osm = j.map(r => {
        const b = r.boundingbox.map(Number);
        const tipo = r.category === "highway" ? "Calle" : r.type === "stream" ? "Quebrada" : r.type === "river" ? "Río"
          : ["suburb", "neighbourhood", "quarter", "village", "hamlet"].includes(r.type) ? "Barrio o sector" : "Lugar";
        return { nombre: r.display_name.split(", ").slice(0, 3).join(", "), tipo,
          punto: [+r.lat, +r.lon], caja: b[0] !== b[1] ? [[b[0], b[2]], [b[1], b[3]]] : null };
      });
      mostrar(p.concat(osm), p.length || osm.length ? null : "No se encontró en el DMQ. Pruebe con otro nombre.");
    } catch (e) {
      mostrar(p, "No se pudo consultar las calles (sin conexión). Se muestran solo los lugares del visualizador.");
    }
  };
  inp.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); buscarCalles(); } if (e.key === "Escape") res.hidden = true; });
  caja.querySelector("button").addEventListener("click", buscarCalles);
}
// ---------------------------------------------------------------- leyendas
function leyenda(id, titulo, clases, circulo) {
  document.getElementById(id).innerHTML = `<b>${titulo}</b>` + clases.map(c => `<span class="caja"><i class="${circulo ? "circulo" : ""}" style="background:${c[1]}"></i>${c[2]}</span>`).join("");
}


// ---------------------------------------------------------------- sesion (solo en la version web con registro)
// Cloudflare Access informa quien entro en /cdn-cgi/access/get-identity y cierra la sesion en /cdn-cgi/access/logout
(function sesion() {
  if (location.protocol !== "https:") return;  // en la computadora (sin registro) no se muestra
  fetch("/cdn-cgi/access/get-identity", { credentials: "include" })
    .then(r => r.ok ? r.json() : null)
    .then(u => {
      const el = document.getElementById("sesion");
      if (!el) return;
      el.innerHTML = `${u && u.email ? u.email + " · " : ""}<a href="/cdn-cgi/access/logout">Cerrar sesión</a>`;
      el.hidden = false;
    })
    .catch(() => {});
})();
