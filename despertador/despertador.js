// "Despertador" en Cloudflare Workers: lanza los procesos de GitHub a la hora exacta.
// GitHub no garantiza sus horarios programados (a veces los retrasa horas o los salta);
// los horarios de Cloudflare si son puntuales. Cada vez que suena, le pide a GitHub correr el proceso.
//   cada 10 minutos  -> Actualizar datos y alertas (actualizar.yml)
//   11h00 UTC (6h00 Quito) -> Pronostico diario (pronostico.yml)
// Secreto necesario en el Worker: GITHUB_TOKEN (token de GitHub con permiso "Actions: Read and write" en el repositorio).
const REPO = "dianalozada1992-design/visualizador-lluvias-cbdmq";

async function lanzar(env, flujo) {
  const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${flujo}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "cbdmq-despertador",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify({ ref: "main" }),
  });
  if (r.status !== 204) throw new Error(`GitHub respondio ${r.status} al lanzar ${flujo}: ${(await r.text()).slice(0, 200)}`);
}

export default {
  async scheduled(evento, env, ctx) {
    if (evento.cron === "0 11 * * *") {
      ctx.waitUntil(lanzar(env, "pronostico.yml"));
    } else {
      ctx.waitUntil(lanzar(env, "actualizar.yml"));
    }
  },
  // abrir la direccion del Worker solo muestra que esta vivo (no lanza nada)
  async fetch() {
    return new Response("Despertador del visualizador de lluvias CBDMQ: activo.", { headers: { "content-type": "text/plain; charset=utf-8" } });
  },
};
