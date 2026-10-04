// Entrega los datos del nivel 2 (historico de lluvias y emergencias) desde el almacen privado.
// La carpeta /historico tiene su propia regla en Cloudflare Access: solo usuarios de nivel 2.
const PERMITIDOS = { "historico.js": "historico", "diario.js": "diario" };

export async function onRequest({ params, env }) {
  const clave = PERMITIDOS[params.archivo];
  if (!clave) return new Response("No encontrado", { status: 404 });
  const texto = await env.LLUVIAS.get(clave);
  if (texto === null) return new Response("// sin datos todavia", { status: 404 });
  return new Response(texto, {
    headers: { "content-type": "application/javascript; charset=utf-8", "cache-control": "private, max-age=3600" },
  });
}
