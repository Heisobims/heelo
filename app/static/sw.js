/**
 * Tixdoo Service Worker
 *
 * Strategy:
 *   - Static assets (/static/*)  → Cache-first (versioned cache)
 *   - Kiosk page                 → Cache on first load, serve from cache offline
 *   - jsQR CDN                   → Cache-first
 *   - Check-in API               → Network-first; queue to IDB on failure (offline)
 *   - All other navigation       → Network-first, fall back to /offline
 *   - All other API              → Network-only (no offline fallback)
 */

const CACHE_VERSION = 'tixdoo-v7';
const OFFLINE_URL   = '/offline';

// Precache: these must all return 200 at install time
const PRECACHE = [
  '/offline',
  '/static/css/main.css',
  '/static/css/dashboard.css',
  '/static/js/main.js',
  'https://cdn.jsdelivr.net/npm/jsqr@1.4.0/dist/jsQR.min.js',
];

// Cache kiosk pages when visited (not pre-cached since we don't know event IDs)
const KIOSK_PATTERN = /\/org\/[^/]+\/events\/[^/]+\/kiosk/;

const CHECKIN_QUEUE_DB = 'tixdoo-checkin-queue';
const CHECKIN_QUEUE_STORE = 'queue';


// ── Install ──────────────────────────────────────────────────────────────────
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION)
      .then(cache => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting())
  );
});


// ── Activate ─────────────────────────────────────────────────────────────────
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(key => key !== CACHE_VERSION)
          .map(key => caches.delete(key))
      )
    ).then(() => self.clients.claim())
  );
});


// ── Fetch ────────────────────────────────────────────────────────────────────
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Only handle same-origin + our CDN
  const isSameOrigin = url.origin === self.location.origin;
  const isJsqrCDN = request.url.startsWith('https://cdn.jsdelivr.net/npm/jsqr');

  // ── Check-in API - network-first with offline queue ─────────────────────
  if (isSameOrigin && url.pathname.includes('/check-in') && request.method === 'POST') {
    event.respondWith(handleCheckin(request));
    return;
  }

  // ── Static assets & CDN - cache-first ────────────────────────────────────
  if ((isSameOrigin && url.pathname.startsWith('/static/')) || isJsqrCDN) {
    event.respondWith(cacheFirst(request));
    return;
  }

  // ── Kiosk page - network-first, cache on success for offline ─────────────
  if (isSameOrigin && KIOSK_PATTERN.test(url.pathname)) {
    event.respondWith(networkFirstWithOfflineFallback(request));
    return;
  }

  // ── Navigation - network-first, offline fallback ──────────────────────────
  if (request.mode === 'navigate') {
    event.respondWith(networkFirstWithOfflineFallback(request));
    return;
  }

  // Everything else: network only
  // (let it fall through to browser default)
});


// ── Background Sync ───────────────────────────────────────────────────────────
self.addEventListener('sync', (event) => {
  if (event.tag === 'checkin-sync') {
    event.waitUntil(drainCheckinQueue());
  }
});


// ── Strategies ────────────────────────────────────────────────────────────────

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_VERSION);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    return new Response('Offline', { status: 503 });
  }
}

async function networkFirstWithOfflineFallback(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_VERSION);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    const cached = await caches.match(request);
    if (cached) return cached;
    const offline = await caches.match(OFFLINE_URL);
    return offline || new Response('Offline', { status: 503, headers: { 'Content-Type': 'text/plain' } });
  }
}

async function handleCheckin(request) {
  const bodyText = await request.text();
  const url = request.url;

  try {
    const response = await fetch(new Request(url, {
      method: 'POST',
      headers: request.headers,
      body: bodyText,
      credentials: 'include',
    }));
    return response;
  } catch {
    // Offline - queue the check-in
    await enqueueCheckin({ url, body: bodyText, timestamp: Date.now() });

    // Return a synthetic response indicating offline queuing
    return new Response(JSON.stringify({
      success: true,
      queued: true,
      data: {
        attendee_name: 'Queued (offline)',
        ticket_type: 'Will sync when online',
        status: 'queued',
      },
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  }
}


// ── IndexedDB queue helpers ───────────────────────────────────────────────────

function openQueueDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(CHECKIN_QUEUE_DB, 1);
    req.onupgradeneeded = (e) => {
      e.target.result.createObjectStore(CHECKIN_QUEUE_STORE, {
        keyPath: 'id', autoIncrement: true,
      });
    };
    req.onsuccess  = (e) => resolve(e.target.result);
    req.onerror    = (e) => reject(e.target.error);
  });
}

async function enqueueCheckin(item) {
  const db = await openQueueDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(CHECKIN_QUEUE_STORE, 'readwrite');
    tx.objectStore(CHECKIN_QUEUE_STORE).add(item);
    tx.oncomplete = resolve;
    tx.onerror    = (e) => reject(e.target.error);
  });
}

// Best-effort registration id for a queued item, purely for reporting a sync
// conflict back to the UI: not used for anything security-sensitive (the
// server independently verifies the QR JWT before ever checking anyone in).
function _queuedItemRegId(body) {
  try {
    const parsed = JSON.parse(body);
    if (parsed.registration_id) return parsed.registration_id;
    if (parsed.qr_token) {
      const payload = JSON.parse(atob(parsed.qr_token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
      return payload.rid || null;
    }
  } catch {
    // ignore
  }
  return null;
}

async function drainCheckinQueue() {
  const db = await openQueueDB();
  const items = await new Promise((resolve, reject) => {
    const tx  = db.transaction(CHECKIN_QUEUE_STORE, 'readonly');
    const req = tx.objectStore(CHECKIN_QUEUE_STORE).getAll();
    req.onsuccess = (e) => resolve(e.target.result);
    req.onerror   = (e) => reject(e.target.error);
  });

  let drained = 0;
  const duplicates = [];

  for (const item of items) {
    try {
      const resp = await fetch(item.url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: item.body,
        credentials: 'include',
      });
      if (resp.ok || resp.status === 409) {
        // Success or already-checked-in: remove from queue
        await new Promise((resolve, reject) => {
          const tx = db.transaction(CHECKIN_QUEUE_STORE, 'readwrite');
          tx.objectStore(CHECKIN_QUEUE_STORE).delete(item.id);
          tx.oncomplete = resolve;
          tx.onerror    = (e) => reject(e.target.error);
        });
        drained++;
        if (resp.status === 409) {
          duplicates.push(_queuedItemRegId(item.body));
        }
      }
    } catch {
      // Still offline: leave in queue
    }
  }

  // Notify all clients of sync completion, including which of the queued
  // check-ins, if any, turned out to already be checked in elsewhere by the
  // time they synced, so the UI can flag it instead of dropping it silently.
  const clients = await self.clients.matchAll();
  clients.forEach(client => client.postMessage({
    type: 'CHECKIN_SYNC_COMPLETE',
    count: drained,
    duplicates,
  }));
}
