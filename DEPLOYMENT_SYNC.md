# Deployment Sync
**Diagrams and flow for Git → Vercel → Telegram Mini App version propagation**

---

## Full Deployment Chain

```
Developer
  │
  ├─ git commit (gitSha: abc1234)
  │
  └─ git push origin main
         │
         ├─ GitHub
         │    ├─ Infrlo auto-deploy (backend)
         │    │    └─ carnavalqmjw.infrlo.com/api/system/version
         │    │         returns: { git_sha: "abc1234" }
         │    │
         │    └─ npx vercel --prod --yes (frontend)
         │         └─ build-vercel.mjs runs:
         │              ├─ computes gitSha = "abc1234"
         │              ├─ injects window.CARNAVAL_BUILD into index.html
         │              ├─ adds ?v=abc1234 to all JS/CSS URLs
         │              └─ uploads to Vercel CDN
         │
         └─ amazing-babbage-tau.vercel.app
              │  Cache-Control: public, max-age=0, must-revalidate
              │  ETag: <new-hash>
              │  X-Build-Id: abc1234
              │
              └─ Telegram Mini App (BotFather URL)
                   │  Telegram WebView opens URL
                   │  Requests index.html:
                   │    → CDN may still serve old HTML for ~30-120s after deploy
                   │    → After propagation: new HTML with window.CARNAVAL_BUILD
                   │    → JS/CSS loaded with ?v=abc1234 (new URLs → forced cache miss)
                   │
                   └─ app.js runs (3s after init):
                        calls getSystemVersion() → /api/system/version
                        frontend SHA: abc1234
                        backend SHA:  abc1234
                        → MATCH: up to date ✓
```

---

## Stale Version Scenario (Before Fix)

```
Developer pushes commit abc1234
  │
  └─ Vercel deploys new HTML (index.html)
       JS URL: /js/app.js (NO version, same as before)
       
Telegram WebView opens Mini App:
  → Requests index.html from CDN
  → CDN still has old HTML (X-Vercel-Cache: HIT, Age: 128s)
  → Loads OLD index.html (still references /js/app.js)
  → Fetches /js/app.js → browser cache returns PREVIOUS version
  → App runs with OLD code ← PROBLEM
  → No window.CARNAVAL_BUILD → no staleness detection
  → No update banner → user doesn't know
```

---

## Fixed Version Scenario (After Fix)

```
Developer pushes commit abc1234
  │
  └─ node scripts/build-vercel.mjs runs:
       injects: window.CARNAVAL_BUILD={gitSha:"abc1234",...}
       changes: /js/app.js?v=abc1234
       changes: /css/app.css?v=abc1234
       
  └─ npx vercel --prod --yes
       CDN purges old HTML cache
       New ETag generated
       
Telegram WebView opens Mini App:
  → Requests index.html
  → CDN serves CACHED old HTML (if within ~120s propagation window):
       Old HTML has /js/app.js?v=old123 → loads OLD JS → runs OLD code
       BUT: after 3s, checkVersionFreshness() runs:
         frontend SHA: old123
         backend SHA:  abc1234 (mismatch!)
         → shows "Доступно обновление Carnaval (abc1234)"
         → user taps "Обновить"
         → window.location.reload(true) ← hard reload
         → new index.html loads with /js/app.js?v=abc1234
         → new JS runs ✓
  → After CDN propagation (~120s):
       index.html is fresh with ?v=abc1234 asset URLs
       WebView fetches /js/app.js?v=abc1234 → NO cache hit (new URL)
       Loads fresh JS ✓
       window.CARNAVAL_BUILD.gitSha = "abc1234"
       backend git_sha = "abc1234"
       → MATCH → no banner shown ✓
```

---

## Timing Analysis

| Event | Time after git push |
|-------|---------------------|
| Vercel build starts | ~0s |
| Vercel build completes | ~30-60s |
| Vercel CDN propagation starts | ~60s |
| Vercel CDN propagation complete (global) | ~60-180s |
| Backend (Infrlo) redeploy completes | ~60-180s |
| User opens Telegram Mini App (worst case) | During CDN propagation |
| User sees update banner (if stale) | 3s after app init |
| User taps "Обновить" → fresh version | ~5-10s |

---

## Telegram WebView Cache Layers

```
Layer 1: Vercel CDN Edge
  → Purged automatically on new deployment
  → Propagation: ~30-120s
  → Headers: Cache-Control: public, max-age=0, must-revalidate

Layer 2: System HTTP Cache (iOS/Android)
  → Respects Cache-Control and ETag headers
  → With ?v= param: URL changed → cache miss → fresh fetch

Layer 3: Telegram App In-Memory Cache
  → Not controllable via HTTP headers
  → ?v= query param defeats this for JS/CSS
  → window.CARNAVAL_BUILD + version check detects staleness
  → User-triggered reload clears in-memory state
```

---

## Key Files

| File | Purpose |
|------|---------|
| `scripts/build-vercel.mjs` | Injects build identity, adds `?v=gitSha`, generates `vercel.json` |
| `carnaval/web/index.html` | Receives injected `window.CARNAVAL_BUILD` at build time |
| `carnaval/web/js/app.js` | Runs `checkVersionFreshness()` 3s after startup |
| `carnaval/web/js/api.js` | `getSystemVersion()` — fetches backend version |
| `carnaval/routers/system_info.py` | `/api/system/version` — backend build identity endpoint |
| `vercel.json` | CDN headers, API rewrite config |
