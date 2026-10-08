// Entrega el archivo mensual de datos de las estaciones (nivel 2, dentro de /historico).
//   indice.json          -> meses y dias guardados
//   cbdmq_AAAA-MM.xlsx    -> estaciones CBDMQ cada 5 minutos, tal como llegan
//   epmaps_AAAA-MM.xlsx   -> estaciones EPMAPS hora por hora
export async function onRequest({ params, env }) {
  const nombre = params.archivo;
  if (nombre === "indice.json") {
    const t = await env.LLUVIAS.get("archivo_indice");
    return new Response(t || '{"meses":{}}', { headers: { "content-type": "application/json", "cache-control": "no-store" } });
  }
  const m = /^(cbdmq|epmaps)_(\d{4}-\d{2})\.xlsx$/.exec(nombre);
  if (!m) return new Response("No encontrado", { status: 404 });
  const datos = await env.LLUVIAS.get(`excel_${m[1]}_${m[2]}`, { type: "arrayBuffer" });
  if (!datos) return new Response("Ese mes no tiene datos guardados.", { status: 404, headers: { "content-type": "text/plain; charset=utf-8" } });
  const titulo = m[1] === "cbdmq" ? "Estaciones_CBDMQ_5min" : "Estaciones_EPMAPS_horario";
  return new Response(datos, { headers: {
    "content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "content-disposition": `attachment; filename="${titulo}_${m[2]}.xlsx"`, "cache-control": "no-store" } });
}
