// Publishes generated demos to Vercel Blob so they stay up without the build sandbox (called by ../publish.py).
//   node publish.mjs site  <slug> <site_dir>    pages -> gen/<slug>/site/... (live-demos-sa serves them at /v2/<slug>/)
//   node publish.mjs pack  <slug> <knowledge>   knowledge pack -> <GEN_PACK_PREFIX>/<slug>/<version>/ (+ manifest.json);
//                                               the shared demo-gen agent loads the newest version on each call
//   node publish.mjs thumb <slug> <jpg>         gallery thumbnail -> gen/<slug>/site/_thumb.jpg (/v2/<slug>/_thumb.jpg)
//   node publish.mjs index <demos.json>         gallery feed -> gen/demos.json (the main page's fallback when the host is off)
//   node publish.mjs delete <slug>              removes all of the above for the demo
// Env: BLOB_READ_WRITE_TOKEN, GEN_PACK_PREFIX. Prints one JSON line.
import { del, list, put } from '@vercel/blob';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { extname, join, relative } from 'node:path';

const PREFIX = process.env.GEN_PACK_PREFIX;
const KEEP_PACKS = 3;
const TYPES = {
  '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8', '.json': 'application/json', '.md': 'text/markdown; charset=utf-8',
  '.txt': 'text/plain; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.gif': 'image/gif', '.avif': 'image/avif', '.ico': 'image/x-icon',
  '.woff': 'font/woff', '.woff2': 'font/woff2', '.ttf': 'font/ttf', '.otf': 'font/otf', '.mp4': 'video/mp4',
  '.webm': 'video/webm', '.mp3': 'audio/mpeg', '.xml': 'application/xml', '.webmanifest': 'application/manifest+json',
};
// The widget asks the page's own origin for a token at /api/token; on live-demos-sa that endpoint serves the classic
// demos, so published copies ask /api/gen-token (which dispatches the shared demo-gen agent with this demo's pack).
const TOKEN_FROM = "new URL('/api/token', me.src)", TOKEN_TO = "new URL('/api/gen-token', me.src)";

const safe = (s) => /^[a-z0-9][a-z0-9-]{0,63}$/.test(s) ? s : (() => { throw new Error(`bad slug ${s}`); })();
const walk = (d) => readdirSync(d).flatMap((n) => statSync(join(d, n)).isDirectory() ? walk(join(d, n)) : [join(d, n)]);
const opts = (p, cache) => ({ access: 'public', addRandomSuffix: false, allowOverwrite: true, cacheControlMaxAge: cache,
  contentType: TYPES[extname(p).toLowerCase()] || 'application/octet-stream' });

async function all(prefix) {
  const out = []; let cursor;
  do { const r = await list({ prefix, cursor, limit: 1000 }); out.push(...r.blobs); cursor = r.hasMore ? r.cursor : undefined; } while (cursor);
  return out;
}
async function pool(items, n, fn) {
  const q = [...items]; await Promise.all(Array.from({ length: n }, async () => { while (q.length) await fn(q.shift()); }));
}
async function drop(urls) { for (let i = 0; i < urls.length; i += 500) await del(urls.slice(i, i + 500)); }

async function site(slug, dir) {
  const base = `gen/${safe(slug)}/site/`, files = walk(dir), keep = new Set(); let patched = 0;
  await pool(files, 8, async (f) => {
    const rel = relative(dir, f).split('\\').join('/'); let body = readFileSync(f);
    if (rel.endsWith('livekit.js') && body.includes(TOKEN_FROM)) { body = Buffer.from(body.toString().split(TOKEN_FROM).join(TOKEN_TO)); patched++; }
    await put(base + rel, body, opts(f, 60)); keep.add(base + rel);
  });
  const stale = (await all(base)).filter((b) => !keep.has(b.pathname)).map((b) => b.url);
  await drop(stale);
  return { files: files.length, removed: stale.length, widgets_patched: patched };
}

async function pack(slug, dir) {
  if (!PREFIX) throw new Error('GEN_PACK_PREFIX is not set');
  const v = new Date().toISOString().replace(/[-:]/g, '').replace('T', '-').slice(0, 15);   // 20261109-170102
  const base = `${PREFIX}/${safe(slug)}/${v}/`;
  const names = readdirSync(dir).filter((n) => /^[\w.-]{1,80}$/.test(n) && statSync(join(dir, n)).isFile());
  await pool(names, 8, (n) => put(base + n, readFileSync(join(dir, n)), opts(n, 31536000)));   // a version never changes
  await put(base + 'manifest.json', JSON.stringify({ slug, v, files: names }), opts('m.json', 31536000));  // last: marks it complete
  const old = await all(`${PREFIX}/${slug}/`);
  const versions = [...new Set(old.map((b) => b.pathname.split('/')[2]))].sort();
  const gone = versions.slice(0, Math.max(0, versions.length - KEEP_PACKS));
  await drop(old.filter((b) => gone.includes(b.pathname.split('/')[2])).map((b) => b.url));
  return { v, files: names.length, pruned: gone.length };
}

async function remove(slug) {
  const blobs = [...await all(`gen/${safe(slug)}/`), ...(PREFIX ? await all(`${PREFIX}/${slug}/`) : [])];
  await drop(blobs.map((b) => b.url));
  return { removed: blobs.length };
}

const [cmd, a, b] = process.argv.slice(2);
const run = { site: () => site(a, b), pack: () => pack(a, b), delete: () => remove(a),
  thumb: async () => ({ url: (await put(`gen/${safe(a)}/site/_thumb.jpg`, readFileSync(b), opts(b, 300))).url }),
  index: async () => ({ url: (await put('gen/demos.json', readFileSync(a), opts(a, 30))).url }) }[cmd];
if (!run) { console.error('usage: publish.mjs site|pack|thumb|index|delete ...'); process.exit(2); }
try { console.log(JSON.stringify({ ok: true, cmd, ...(await run()) })); }
catch (e) { console.log(JSON.stringify({ ok: false, cmd, error: String(e.message || e).slice(0, 300) })); process.exit(1); }
