# Hosting

- **App:** Vercel (Hobby), project `magnolia-analytics`, region `lhr1`, entry point `wsgi.py`.
  Pushes to `master` deploy via `.github/workflows/deploy.yml` (Vercel deploy hook).
- **Database:** Neon Postgres (free), connected through the Vercel Marketplace (`DATABASE_URL`).
- **Domain:** `magnoliaanalytics.golf` DNS is on Cloudflare. The Worker in
  `cloudflare-worker/` proxies the domain to the Vercel app.
  Deploy it with `npx wrangler deploy` from that folder.
