// HTML pages of AI-generated demos (/v2/<slug>/...), read from Vercel Blob (gen/<slug>/site/, published by
// generator-v2/host/publish.py). Blob serves .html as a download with a locked-down CSP, so pages come through here with
// normal headers; images, CSS and JS are proxied straight from Blob by vercel.json rewrites.
//   GET /api/gen-page?slug=<slug>&path=<dir or file.html>   (vercel.json maps /v2/<slug>/<path> here)
const BASE = process.env.GEN_BLOB_BASE || 'https://88ev414hvkdji1jn.public.blob.vercel-storage.com';

export default async function handler(req, res) {
  const q = new URL(req.url, 'http://x').searchParams;
  const slug = q.get('slug') || '', path = (q.get('path') || '').replace(/^\/+|\/+$/g, '');
  if (!/^[a-z0-9][a-z0-9-]{0,63}$/.test(slug) || path.split('/').some((s) => s === '..' || s === '.')) return notFound(res);
  const file = /\.html?$/i.test(path) ? path : (path ? path + '/' : '') + 'index.html';
  const r = await fetch(`${BASE}/gen/${slug}/site/${file.split('/').map(encodeURIComponent).join('/')}`);
  if (!r.ok) return notFound(res);
  res.statusCode = 200;
  res.setHeader('Content-Type', 'text/html; charset=utf-8');
  res.setHeader('Cache-Control', 'public, max-age=0, s-maxage=30, stale-while-revalidate=60');   // edits show within ~30 s
  res.end(Buffer.from(await r.arrayBuffer()));
}

function notFound(res) {
  res.statusCode = 404;
  res.setHeader('Content-Type', 'text/html; charset=utf-8');
  res.setHeader('Cache-Control', 'public, max-age=0, s-maxage=30');
  res.end('<!doctype html><meta charset=utf-8><title>Demo not found</title><body style="font:16px system-ui;background:#070707;color:#e8e9eb;display:grid;place-items:center;height:100vh;margin:0"><p>This demo isn\'t available (it may have been deleted). <a style="color:#1fd5f9" href="/">All demos</a></p>');
}
