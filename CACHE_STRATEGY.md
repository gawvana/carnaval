# Cache Strategy
**Version:** 1.0  
**Applies to:** Carnaval Mini App — Vercel (frontend) + Infrlo (backend)

---

## Core Principle

```
HTML entry point    → short cache + must-revalidate (always fresh)
Versioned JS/CSS    → query-busted per deployment (forced cache miss)
API responses       → no-store (never cached)
SSE stream          → no-cache (streaming, no caching)
```

---

## HTML (`index.html`)

```
Cache-Control: public, max-age=0, must-revalidate
```

- Browser always revalidates with `ETag` before using cached copy
- Vercel CDN auto-purges edge cache on new deployment
- `window.CARNAVAL_BUILD` injected at build time — uniquely identifies deployment
- **Do NOT add `immutable` or long `max-age` to HTML**

---

## JS / CSS Assets — Phase 1 (current)

All local asset URLs have `?v=<gitSha>` appended by `build-vercel.mjs`:

```html
<!-- Before build -->
<script src="/js/app.js"></script>

<!-- After build (example) -->
<script src="/js/app.js?v=899b53f"></script>
```

```
Cache-Control: public, max-age=0, must-revalidate
X-Build-Id: <buildId>
```

**Effect:** Each new deployment has a different `?v=` param → Telegram WebView treats it as a new URL → guaranteed cache miss → fresh asset fetched.

---

## JS / CSS Assets — Phase 2 (future ideal)

Use a bundler (Vite, esbuild) to produce content-hashed filenames:

```html
<script src="/assets/app.a1b2c3d4.js"></script>
```

```
Cache-Control: public, max-age=31536000, immutable
```

**Effect:** Fastest possible delivery. URLs are permanent per content — no revalidation needed.

---

## API Responses (`/api/*`)

```
Cache-Control: no-store, no-cache, must-revalidate
Pragma: no-cache
```

Set in `vercel.json` headers for `/api/(.*)` and in backend middleware.  
**Never cached** — always fetched from Infrlo backend.

### Critical no-cache endpoints

| Endpoint | Reason |
|----------|--------|
| `/api/system/version` | Must always return current backend build |
| `/api/health` | Live system state |
| `/api/live/*` | Real-time telemetry |
| `/api/account/state` | Authentication state |

---

## SSE (`/api/events`)

```
Cache-Control: no-cache
Content-Type: text/event-stream
Connection: keep-alive
```

SSE is a streaming protocol — never cached by any layer.

---

## Vercel CDN Edge Cache

- Vercel **auto-purges** edge cache on every new successful deployment
- Propagation time: ~30–120 seconds globally
- **Do NOT use `s-maxage`** or `Surrogate-Control` on HTML — this bypasses auto-purge

---

## Telegram WebView Cache Behavior

Telegram uses system WebView (WKWebView on iOS, Chrome WebView on Android) with its own HTTP cache layer.

| Mitigation | Implementation |
|-----------|----------------|
| Asset URL versioning | `?v=<gitSha>` query param — forces cache miss on new builds |
| Startup version check | Frontend SHA vs backend SHA compared on every app open |
| Update banner | User-triggered reload when stale detected |
| Loop protection | `sessionStorage` flag — one controlled reload maximum |

---

## Anti-Patterns (DO NOT DO)

```js
// ❌ Infinite reload loop
setInterval(() => window.location.reload(), 30000);

// ❌ Random query params on every API request
fetch(`/api/health?t=${Date.now()}`);

// ❌ Disabling all caching globally
headers: [{ key: 'Cache-Control', value: 'no-store' }]  // on static assets

// ❌ Hardcoded "latest version" string
window.CARNAVAL_BUILD = { version: "2.1.0" };  // without gitSha
```
