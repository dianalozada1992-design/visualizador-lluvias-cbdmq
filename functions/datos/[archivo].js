// Entrega los datos del nivel 1 (monitoreo) desde el almacen privado de Cloudflare.
// Esta direccion queda protegida por Cloudflare Access (solo usuarios registrados).
const PERMITIDOS = { "capas.js": "capas", "tiempo_real.js": "tiempo_real" };

export async function onRequest({ params, env }) {
  const clave = PERMITIDOS[params.archivo];
  if (!clave) return new Response("No encontrado", { status: 404 });
  const texto = await env.LLUVIAS.get(clave);
  if (texto === null) return new Response("// sin datos todavia", { status: 404 });
  return new Response(texto, {
    headers: { "content-type": "application/javascript; charset=utf-8", "cache-control": "no-store" },
  });
}
