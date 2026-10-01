# Deployment & Cache Audit
**Audit Time:** 2026-10-01T14:14Z  
**Auditor:** AGENT-VERCEL + AGENT-CACHE forensic pass

---

## Git / Deployment State

| Source | Value |
|--------|-------|
| Git HEAD (local) | `899b53f` |
| Last commit message | `fix(remediation): atomic update, plugin parity, automation builder, strict health, zero-emoji SVG UI - 181 tests pass` |
| Vercel Production URL | https://amazing-babbage-tau.vercel.app |
| Backend (Infrlo) URL | https://carnavalqmjw.infrlo.com |
| Mini App URL (assumed) | https://amazing-babbage-tau.vercel.app |

---

## Cache Headers — Observed (Pre-Fix)

| Resource | Cache-Control | X-Vercel-Cache | ETag | Age |
|----------|---------------|----------------|------|-----|
| `index.html` | `public, max-age=0, must-revalidate` | **HIT** | `6cb5647a...` | **128s** |
| `/js/app.js` | `public, max-age=0, must-revalidate` | MISS | `8a462380...` | 0 |
| `/css/app.css` | `public, max-age=0, must-revalidate` | MISS | `63317dab...` | 0 |

> [!WARNING]
> `X-Vercel-Cache: HIT` on HTML with Age=128s means Vercel's CDN edge returned a cached copy. During new deployment rollout, Telegram WebView may receive the old HTML from CDN edge nodes that haven't propagated yet.

---

## Asset Versioning (Pre-Fix)

| File | URL | Fingerprinted | Issue |
|------|-----|---------------|-------|
| `app.js` | `/js/app.js` | ❌ NO | Same URL = WebView may skip revalidation |
| `app.css` | `/css/app.css` | ❌ NO | Same URL = WebView may skip revalidation |
| `tokens.css` | `/css/tokens.css` | ❌ NO | Same URL |
| All other CSS | `/css/*.css` | ❌ NO | Same URLs |

---

## Service Worker

| Check | Result |
|-------|--------|
| `sw.js` | ✅ Not found |
| `service-worker.js` | ✅ Not found |
| Workbox | ✅ Not found |
| `_headers` file | ✅ Not found |
| `_redirects` file | ✅ Not found |

**No service worker present** — service worker is NOT the root cause.

---

## Root Cause Analysis

### P0 — Critical (confirmed)

1. **No build identity in HTML**  
   Frontend had no `window.CARNAVAL_BUILD` — impossible to detect whether Telegram is serving a stale build or a fresh one. Zero diagnostic visibility.

2. **Unversioned asset URLs**  
   JS/CSS served as `/js/app.js`, `/css/app.css` (no hash, no query param). Telegram WebView sees the same URL on every load. If the browser/WebView memory-caches it, it will never fetch the updated file — even if the content changed.

3. **No `/api/system/version` endpoint**  
   No backend-advertised version → frontend cannot compare itself to backend → no staleness detection possible.

4. **No startup version check**  
   Even if staleness were detectable, no code checked for it. User had no signal when running stale code.

5. **No update banner / user action**  
   Even if stale state were known, user had no way to self-recover.

### P1 — High

6. **`X-Vercel-Cache: HIT` on HTML (Age=128s)**  
   CDN edge propagation delay on new deployments. Vercel auto-purges on deploy, but edge nodes can lag 30–120s. Telegram Mini App launched during this window gets old HTML.

### P2 — Medium

7. **JS/CSS Cache-Control identical to HTML**  
   Both get `max-age=0, must-revalidate`. This is correct behavior, but relies on the browser sending revalidation requests. Telegram WebView may not always do this if it considers the resource "fresh enough" by its own logic.

---

## Fixes Applied

| Fix | File | Description |
|-----|------|-------------|
| Build identity injection | `scripts/build-vercel.mjs` | `window.CARNAVAL_BUILD` injected into `index.html` at build time |
| Asset cache-busting | `scripts/build-vercel.mjs` | `?v=<gitSha>` appended to all `/js/*.js` and `/css/*.css` URLs |
| JS/CSS-specific headers | `scripts/build-vercel.mjs` | Added `X-Build-Id` response header for JS/CSS |
| `/api/system/version` | `carnaval/routers/system_info.py` | Public endpoint returning backend gitSha, version, environment |
| Startup version check | `carnaval/web/js/app.js` | Compares `window.CARNAVAL_BUILD.gitSha` vs backend `/api/system/version` |
| Update banner | `carnaval/web/js/app.js` | Shows banner when stale; user-triggered reload (no auto-loop) |
| Loop protection | `carnaval/web/js/app.js` | `sessionStorage` flag prevents infinite reload after update |
| Diagnostic CSS | `carnaval/web/css/components.css` | `.diag-card` / `.diag-row` styles |

---

## Telegram Mini App URL

> [!IMPORTANT]
> **MANUAL ACTION REQUIRED** if the Mini App URL configured in BotFather is NOT `https://amazing-babbage-tau.vercel.app`
>
> Verify in Telegram BotFather:
> 1. `/mybots` → select your bot
> 2. `Bot Settings` → `Menu Button` → `Configure menu button`
> 3. URL must be: `https://amazing-babbage-tau.vercel.app`
> 4. If it points to any other URL (preview, old domain, localhost) — update it.
>
> We cannot verify or change this without bot owner credentials.
