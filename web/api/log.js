// Stores one demo call's step log (the agent's sessions/<room>/events.jsonl) in the project's private Blob store, so
// calls served by LiveKit Cloud can be reviewed afterwards (the container's own disk is gone when it shuts down).
//   POST /api/log?room=<room>   header x-log-secret: <LOG_SECRET>   body: the JSONL text
import { put } from '@vercel/blob';
import { createHash, timingSafeEqual } from 'node:crypto';

export const config = { api: { bodyParser: false } };

const same = (a, b) => { const h = (s) => createHash('sha256').update(String(s ?? '')).digest(); return timingSafeEqual(h(a), h(b)); };

export default async function handler(req, res) {
  if (req.method !== 'POST') { res.statusCode = 405; return res.end(); }
  if (!process.env.LOG_SECRET || !same(req.headers['x-log-secret'], process.env.LOG_SECRET)) { res.statusCode = 401; return res.end(); }
  const room = String(req.query?.room || new URL(req.url, 'http://x').searchParams.get('room') || '').replace(/[^a-zA-Z0-9_-]/g, '').slice(0, 64);
  if (!room) { res.statusCode = 400; return res.end('room required'); }
  const chunks = []; let size = 0;
  for await (const c of req) { size += c.length; if (size > 4_000_000) { res.statusCode = 413; return res.end(); } chunks.push(c); }
  // one file per call, replaced on every upload (the agent uploads every 30 s during the call and once at the end)
  const blob = await put(`calls/${room}.jsonl`, Buffer.concat(chunks), { access: 'private', contentType: 'application/x-ndjson', addRandomSuffix: false, allowOverwrite: true });
  res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify({ ok: true, pathname: blob.pathname }));
}
