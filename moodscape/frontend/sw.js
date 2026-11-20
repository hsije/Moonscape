// Moodscape Service Worker
// 全部资源本地化：断网 / 无 CDN 时岛屿仍可渲染。
const CACHE_NAME = 'moodscape-cache-v3';
const ASSETS = [
  './',
  './index.html',
  './style.css',
  './config.js',
  './main.js',
  './manifest.json',
  './icon.png',
  './vendor/three/three.module.js',
  './vendor/three/three.core.js',
  './vendor/three/addons/controls/OrbitControls.js',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(ASSETS))
      .then(() => self.skipWaiting())
  );
});

// 清理旧版本缓存，避免 v1 的 CDN 条目继续生效
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  // 接口请求不进缓存：情绪数据必须实时
  if (req.method !== 'GET' || /\/(analyze|island|release|bond|bottle|action|subscribe|entitlements|seed|print|mirror|ws)\b/.test(new URL(req.url).pathname)) {
    return;
  }

  const url = new URL(req.url);
  const isDoc = req.mode === 'navigate' || /\.(html|js|css|json)$/.test(url.pathname);

  // 文档与脚本走网络优先：避免缓存把旧界面钉死（断网时回落缓存）
  if (isDoc && url.origin === self.location.origin) {
    event.respondWith(
      fetch(req).then((res) => {
        if (res && res.ok) {
          const copy = res.clone();
          caches.open(CACHE_NAME).then((c) => c.put(req, copy));
        }
        return res;
      }).catch(() => caches.match(req).then((hit) => hit || caches.match('./index.html')))
    );
    return;
  }

  // 其余静态资源（three.js、图标）缓存优先，离线也能渲染
  event.respondWith(
    caches.match(req).then((hit) => hit || fetch(req).then((res) => {
      if (res && res.ok && url.origin === self.location.origin) {
        const copy = res.clone();
        caches.open(CACHE_NAME).then((c) => c.put(req, copy));
      }
      return res;
    }).catch(() => caches.match('./index.html')))
  );
});
