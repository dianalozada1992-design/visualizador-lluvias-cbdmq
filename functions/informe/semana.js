// Entrega el informe semanal de lluvias y emergencias mas reciente (PDF) desde el almacen privado (nivel 1).
export async function onRequest({ env }) {
  const pdf = await env.LLUVIAS.get("informe_semanal_pdf", { type: "arrayBuffer" });
  if (!pdf) return new Response("Todavía no hay informe semanal (se genera los lunes).", { status: 404, headers: { "content-type": "text/plain; charset=utf-8" } });
  const fecha = (await env.LLUVIAS.get("informe_semanal_fecha")) || "semana";
  return new Response(pdf, {
    headers: { "content-type": "application/pdf", "content-disposition": `inline; filename="informe_semanal_${fecha}.pdf"`, "cache-control": "no-store" },
  });
}
