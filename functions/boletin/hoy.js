// Entrega el boletin de lluvias y emergencias mas reciente (PDF) desde el almacen privado (nivel 1).
export async function onRequest({ env }) {
  const pdf = await env.LLUVIAS.get("boletin_pdf", { type: "arrayBuffer" });
  if (!pdf) return new Response("Todavía no hay boletín generado.", { status: 404, headers: { "content-type": "text/plain; charset=utf-8" } });
  const fecha = (await env.LLUVIAS.get("boletin_pdf_fecha")) || "hoy";
  return new Response(pdf, {
    headers: { "content-type": "application/pdf", "content-disposition": `inline; filename="boletin_lluvias_emergencias_${fecha}.pdf"`,
               "cache-control": "no-store" },
  });
}
