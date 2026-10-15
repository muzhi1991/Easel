/* Generated with a content-derived version by Vite. Only app shell assets belong here. */
const FILES = __PRECACHE_FILES__;
const VERSION = '__BUILD_VERSION__';
const ROOT = self.registration.scope;
const PREFIX = `easel-shell:${ROOT}:`;
const CACHE = PREFIX + VERSION;
const URLS = FILES.map(path => new URL(path, ROOT).href);
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(URLS)));
});
self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) {
      if (key.startsWith(PREFIX) && key !== CACHE) await caches.delete(key);
    }
    await self.clients.claim();
  })());
});
self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  const root = new URL(ROOT);
  if (url.origin !== root.origin) return;
  const navigation = request.mode === 'navigate' && (url.pathname === root.pathname || url.pathname === root.pathname + 'index.html');
  // Never cache API/SSE responses, uploads, credentials or generated user files.
  if (!navigation && !URLS.includes(url.href)) return;
  const key = navigation ? ROOT : url.href;
  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const cached = await cache.match(key);
    return cached || fetch(request);
  })());
});
async function canUpdate(client) {
  return new Promise(resolve => {
    const channel = new MessageChannel();
    const timer = setTimeout(() => { channel.port1.close(); resolve(false); }, 2500);
    channel.port1.onmessage = event => {
      clearTimeout(timer); channel.port1.close(); resolve(event.data?.safe === true);
    };
    client.postMessage({ type: 'CAN_UPDATE' }, [channel.port2]);
  });
}
self.addEventListener('message', event => {
  if (event.data?.type !== 'UPDATE') return;
  event.waitUntil((async () => {
    const clients = (await self.clients.matchAll({ type: 'window', includeUncontrolled: true }))
      .filter(client => client.url.startsWith(ROOT));
    const safe = (await Promise.all(clients.map(canUpdate))).every(Boolean);
    event.ports[0]?.postMessage({ safe });
    if (safe) await self.skipWaiting();
  })());
});
