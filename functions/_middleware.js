// Seguridad adicional: solo deja pasar a quien entro por Cloudflare Access (registro con correo).
// Cloudflare Access agrega la cabecera Cf-Access-Jwt-Assertion a cada visita autorizada;
// sin ella (por ejemplo si Access no esta configurado) la pagina y los datos quedan cerrados.
const CERRADO = `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>Acceso restringido</title></head>
<body style="font-family:Segoe UI,Arial,sans-serif;background:#f3f6fa;color:#1b2631;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:16px">
<div style="background:#fff;border:1px solid #d7dfea;border-radius:12px;padding:28px;max-width:440px;text-align:center">
<div style="background:#1f3f73;color:#fff;font-weight:800;border-radius:8px;padding:8px 10px;display:inline-block">CBDMQ</div>
<h1 style="font-size:20px;color:#1f3f73">Visualizador de lluvias: acceso restringido</h1>
<p>Esta página es solo para personal autorizado de la Dirección de Gestión de Riesgos.</p>
<p style="color:#5d6d7e;font-size:13px">Si necesita acceso, solicítelo a la administradora del visualizador.</p></div></body></html>`;

export async function onRequest(ctx) {
  if (!ctx.request.headers.get("Cf-Access-Jwt-Assertion")) {
    return new Response(CERRADO, { status: 403, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } });
  }
  return ctx.next();
}
