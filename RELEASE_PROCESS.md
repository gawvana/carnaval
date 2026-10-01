# Release Process
**Version:** 1.0  
**Applies to:** Carnaval Mini App — full stack (frontend + backend)

---

## Overview

```
Developer machine
  └── git commit
  └── git push origin main
         └── GitHub (gawvana/carnaval)
               └── Infrlo auto-deploy (backend: carnavalqmjw.infrlo.com)
               └── Vercel deploy (frontend: amazing-babbage-tau.vercel.app)
                      └── Telegram Mini App (via BotFather URL)
```

---

## Standard Release Checklist

### 1. Test locally

```powershell
python -m pytest -q --tb=short  # must be 100% green (≥181 tests)
```

### 2. Build Vercel artifacts

```powershell
node scripts/build-vercel.mjs
```

**Expected output includes:**
```
[Vercel Build] Build identity: version=2.1.0 gitSha=<sha> buildId=<id> env=production
[Vercel Build] Configuring /api/* rewrite -> https://carnavalqmjw.infrlo.com/api/*
[Vercel Build] vercel.json generated successfully.
[Vercel Build] Injected window.CARNAVAL_BUILD into index.html (gitSha=<sha>)
[Vercel Build] Added ?v=<sha> cache-busting to all local JS/CSS asset URLs
[Vercel Build] .vercel/output Build Output API v3 created.
[Vercel Build] Build finished successfully.
```

### 3. Commit and push

```powershell
git add -A
git commit -m "type(scope): description"
git push origin main
```

### 4. Deploy to Vercel

```powershell
npx vercel --prod --yes
```

### 5. Verify deployment — REQUIRED

```powershell
# a) HTML contains build identity
curl.exe -s https://amazing-babbage-tau.vercel.app/ | Select-String 'CARNAVAL_BUILD'
# Expected: window.CARNAVAL_BUILD={version:"2.1.0",gitSha:"<sha>",...}

# b) JS URLs contain ?v= param (cache-busting)
curl.exe -s https://amazing-babbage-tau.vercel.app/ | Select-String '?v='
# Expected: /js/app.js?v=<sha>, /css/app.css?v=<sha>, etc.

# c) HTTP 200 on production
curl.exe -s -o NUL -w "%{http_code}" https://amazing-babbage-tau.vercel.app
# Expected: 200

# d) Backend version endpoint (if backend redeployed)
curl.exe -s https://carnavalqmjw.infrlo.com/api/system/version
# Expected: {"ok":true,"git_sha":"<sha>",...}

# e) Cache headers
curl.exe -sI https://amazing-babbage-tau.vercel.app/ | Select-String 'cache|x-vercel|etag'
# Expected: Cache-Control: public, max-age=0, must-revalidate; X-Build-Id: <buildId>
```

### 6. Post-Deploy Checklist

- [ ] `window.CARNAVAL_BUILD.gitSha` matches pushed commit
- [ ] All JS/CSS URLs have `?v=<gitSha>` query param
- [ ] `/api/system/version` returns correct `git_sha` (backend side)
- [ ] `X-Vercel-Cache` shows new ETag vs previous deployment
- [ ] Open production URL in incognito → verify new build loads
- [ ] Open Telegram Mini App → verify update banner shows (if stale) OR new version loads directly

---

## Infrlo Backend Deployment

Backend is deployed separately on Infrlo from the same `main` branch.

After `git push origin main`:
- If Infrlo is configured for auto-deploy on push → redeploy happens automatically (~1–3 min)
- If manual trigger required → Infrlo dashboard → Project → Redeploy

**Environment variables to set in Infrlo:**
```
CARNAVAL_ENV=production
CARNAVAL_APP_VERSION=2.1.0
```
> `CARNAVAL_GIT_SHA` and `CARNAVAL_BUILD_ID` are auto-computed at startup via `git rev-parse` subprocess.

---

## Rollback Procedure

```powershell
# Option 1: Vercel rollback to previous deployment
npx vercel rollback

# Option 2: Revert git commit and redeploy
git revert HEAD
git push origin main
npx vercel --prod --yes
```

---

## Telegram Mini App URL Verification

> [!IMPORTANT]
> The Telegram Mini App URL **must** match the Vercel production domain.
>
> **Verify in BotFather:**
> 1. `/mybots` → select your bot
> 2. `Bot Settings` → `Menu Button` → view configured URL
> 3. Must be exactly: `https://amazing-babbage-tau.vercel.app`
> 4. Must NOT be a preview URL like `https://amazing-babbage-git-main-*.vercel.app`

---

## Version Sync Architecture

After this release:

```
Build time:
  scripts/build-vercel.mjs
    → computes gitSha from git rev-parse
    → injects window.CARNAVAL_BUILD into index.html
    → adds ?v=<gitSha> to all JS/CSS asset URLs

Runtime (Telegram WebView opens the app):
  index.html loads → window.CARNAVAL_BUILD is available
  app.js starts → after 3s calls getSystemVersion() via api.js
    → /api/system/version (no-store, always fresh from backend)
    → compares frontend gitSha vs backend git_sha
    → if mismatch: shows "Доступно обновление Carnaval" banner
    → user taps "Обновить" → safeReload() → page reloads with new assets
    → sessionStorage flag prevents immediate re-banner after reload
```

---

## Definition of Done

| Check | Requirement |
|-------|-------------|
| Tests | ≥181 passed, 0 failed |
| Git push | `main` branch |
| Vercel production | Correct commit deployed |
| HTML | Contains `window.CARNAVAL_BUILD` with correct `gitSha` |
| JS/CSS URLs | Contain `?v=<gitSha>` |
| `/api/system/version` | Returns correct `git_sha` |
| HTTP status | Production URL returns 200 |
| No service worker | Not serving stale content |
| Update banner | Shows when frontend SHA ≠ backend SHA |
| No infinite reload | `sessionStorage` flag prevents loops |
| Telegram Mini App | Shows new version (or banner prompting update) |
