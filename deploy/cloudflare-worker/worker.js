// Serves magnoliaanalytics.golf from the Vercel deployment.
// The domain's DNS stays on Cloudflare (proxied); this Worker forwards every
// request to the Vercel app and passes the response straight back.
const ORIGIN = 'https://magnolia-analytics-indol.vercel.app';
const APEX = 'magnoliaanalytics.golf';

export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (url.hostname === 'www.' + APEX) {
      url.hostname = APEX;
      return Response.redirect(url.toString(), 301);
    }
    const target = new URL(url.pathname + url.search, ORIGIN);
    const headers = new Headers(request.headers);
    headers.delete('host');
    headers.set('X-Forwarded-Host', url.host);
    const init = { method: request.method, headers, redirect: 'manual' };
    if (!['GET', 'HEAD'].includes(request.method)) init.body = request.body;
    const resp = await fetch(target, init);
    const out = new Response(resp.body, resp);
    const loc = out.headers.get('Location');
    if (loc && loc.startsWith(ORIGIN)) out.headers.set('Location', url.origin + loc.slice(ORIGIN.length));
    return out;
  },
};
