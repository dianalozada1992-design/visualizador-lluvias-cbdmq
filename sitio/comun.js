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
function mapaBase(id) {
  const m = L.map(id, { zoomControl: true, minZoom: 9 }).setView([-0.2, -78.5], 10);
  L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
    { attribution: "Esri, HERE, Garmin, &copy; OpenStreetMap", maxZoom: 16 }).addTo(m);
  L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}",
    { maxZoom: 16, pane: "shadowPane", opacity: .8 }).addTo(m);
  m.fitBounds(L.geoJSON(CAPAS.brigadas).getBounds(), { padding: [6, 6] });
  return m;
}
// ---------------------------------------------------------------- leyendas
function leyenda(id, titulo, clases, circulo) {
  document.getElementById(id).innerHTML = `<b>${titulo}</b>` + clases.map(c => `<span class="caja"><i class="${circulo ? "circulo" : ""}" style="background:${c[1]}"></i>${c[2]}</span>`).join("");
}

