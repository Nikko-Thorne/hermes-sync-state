// Cloudflare Worker for hermes-sync Brave adapter
// Deploy: npx wrangler deploy
// Requires: R2 bucket bound as SYNC_BLOB

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const hash = url.pathname.slice(1); // /:hash

    if (!hash || hash.length > 64) {
      return new Response("Bad request", { status: 400 });
    }

    // PUT — store encrypted blob
    if (request.method === "PUT") {
      const body = await request.arrayBuffer();
      if (body.byteLength > 50 * 1024 * 1024) { // 50MB cap
        return new Response("Too large", { status: 413 });
      }
      await env.SYNC_BLOB.put(hash, body);
      return new Response("OK", { status: 200 });
    }

    // GET — retrieve encrypted blob
    if (request.method === "GET") {
      const obj = await env.SYNC_BLOB.get(hash);
      if (!obj) return new Response("Not found", { status: 404 });
      return new Response(obj.body, {
        headers: { "Content-Type": "application/octet-stream" }
      });
    }

    return new Response("Method not allowed", { status: 405 });
  }
};
