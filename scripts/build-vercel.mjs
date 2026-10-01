/**
 * scripts/build-vercel.mjs
 *
 * Production build script for Vercel deployment of Carnaval Mini App frontend.
 *
 * - Sets up external rewrite for /api/* -> https://<backend-origin>/api/*
 * - Implements Vercel Build Output API v3 (.vercel/output)
 * - Ensures NO secrets are bundled into client-side code
 * - Applies strict security headers & no-store caching on /api/*
 * - Injects build identity (window.CARNAVAL_BUILD) into index.html
 * - Adds ?v=<gitSha> cache-busting to all local JS/CSS asset URLs
 */

import { cpSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execSync } from 'node:child_process';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT_DIR = resolve(__dirname, '..');
const WEB_DIR = join(ROOT_DIR, 'carnaval', 'web');
const VERCEL_OUTPUT_DIR = join(ROOT_DIR, '.vercel', 'output');
const VERCEL_STATIC_DIR = join(VERCEL_OUTPUT_DIR, 'static');

// ─── 0. Resolve build identity ────────────────────────────────────────────────
const gitSha = (() => {
  // Vercel injects VERCEL_GIT_COMMIT_SHA in CI environments
  const vecelSha = process.env.VERCEL_GIT_COMMIT_SHA;
  if (vecelSha) return vecelSha.slice(0, 7);
  try {
    return execSync('git rev-parse --short HEAD', { cwd: ROOT_DIR }).toString().trim();
  } catch {
    return 'unknown';
  }
})();

const buildId = process.env.VERCEL_DEPLOYMENT_ID || gitSha;
const buildTime = new Date().toISOString();

let appVersion = process.env.CARNAVAL_APP_VERSION;
let apiContract = 5;
try {
  const vContent = readFileSync(join(ROOT_DIR, 'carnaval', 'version.py'), 'utf-8');
  const vMatch = vContent.match(/APP_VERSION\s*(?::\s*str)?\s*=\s*["']([^"']+)["']/);
  if (vMatch) appVersion = vMatch[1];
  const cMatch = vContent.match(/API_CONTRACT\s*(?::\s*int)?\s*=\s*(\d+)/);
  if (cMatch) apiContract = parseInt(cMatch[1], 10);
} catch {}
appVersion = appVersion || '2.1.0';

const environment = process.env.VERCEL_ENV || process.env.CARNAVAL_ENV || 'production';

console.log(`[Vercel Build] Build identity: version=${appVersion} gitSha=${gitSha} buildId=${buildId} env=${environment} contract=${apiContract}`);

// ─── 1. Audit environment variables to prevent secret leakage ─────────────────
const FORBIDDEN_SECRET_KEYS = [
  'TG_BOT_TOKEN',
  'TELEGRAM_BOT_TOKEN',
  'GOLDEN_KEY',
  'FUNPAY_GOLDEN_KEY',
  'FUNPAY_PASSWORD',
  'PANEL_PASSWORD',
  'MASTER_KEY',
  'SESSION_SECRET',
  'PROXY_PASSWORD',
];

for (const key of FORBIDDEN_SECRET_KEYS) {
  if (process.env[key]) {
    console.warn(`[SECURITY WARNING] Found server-side secret '${key}' in Vercel build environment!`);
    console.warn(`Removing '${key}' from build environment to prevent frontend leakage.`);
    delete process.env[key];
  }
}

// ─── 2. Determine backend origin ──────────────────────────────────────────────
const rawBackend = (
  process.env.BACKEND_PUBLIC_ORIGIN ||
  process.env.INFR_BACKEND_URL ||
  process.env.CARNAVAL_API_URL ||
  'https://carnavalqmjw.infrlo.com'
).trim();

const backendOrigin = rawBackend.replace(/\/+$/, '');
console.log(`[Vercel Build] Configuring /api/* rewrite -> ${backendOrigin}/api/*`);

// ─── 3. Update vercel.json in repository root ─────────────────────────────────
const vercelConfig = {
  $schema: 'https://openapi.vercel.sh/vercel.json',
  version: 2,
  framework: null,
  outputDirectory: 'carnaval/web',
  cleanUrls: true,
  buildCommand: 'node scripts/build-vercel.mjs',
  rewrites: [
    {
      source: '/api/:path*',
      destination: `${backendOrigin}/api/:path*`,
    },
  ],
  headers: [
    {
      // API responses: never cached
      source: '/api/(.*)',
      headers: [
        { key: 'Cache-Control', value: 'no-store, no-cache, must-revalidate' },
      ],
    },
    {
      // JS/CSS: must-revalidate (will use ETag). Combined with ?v= query busting,
      // Telegram WebView is forced to revalidate on each new deployment.
      source: '/js/(.*)',
      headers: [
        { key: 'Cache-Control', value: 'public, max-age=0, must-revalidate' },
        { key: 'X-Build-Id', value: buildId },
      ],
    },
    {
      source: '/css/(.*)',
      headers: [
        { key: 'Cache-Control', value: 'public, max-age=0, must-revalidate' },
        { key: 'X-Build-Id', value: buildId },
      ],
    },
    {
      // HTML entry point: always revalidate
      source: '/',
      headers: [
        { key: 'Cache-Control', value: 'public, max-age=0, must-revalidate' },
        { key: 'X-Build-Id', value: buildId },
      ],
    },
    {
      // All other static responses: security headers
      source: '/(.*)',
      headers: [
        { key: 'X-Content-Type-Options', value: 'nosniff' },
        { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
        {
          key: 'Content-Security-Policy',
          value:
            "default-src 'self'; script-src 'self' 'unsafe-inline' https://telegram.org; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https: blob:; connect-src 'self' https:; frame-ancestors https://web.telegram.org https://*.telegram.org telegram:;",
        },
      ],
    },
  ],
};

writeFileSync(join(ROOT_DIR, 'vercel.json'), JSON.stringify(vercelConfig, null, 2) + '\n');
console.log('[Vercel Build] vercel.json generated successfully.');

// ─── 4. Generate Build Output API v3 (.vercel/output) ─────────────────────────
try {
  mkdirSync(VERCEL_STATIC_DIR, { recursive: true });
  cpSync(WEB_DIR, VERCEL_STATIC_DIR, { recursive: true });

  // ── 4a. Inject build identity into index.html ──
  const indexPath = join(VERCEL_STATIC_DIR, 'index.html');
  let html = readFileSync(indexPath, 'utf-8');

  // Build identity block — injected before </head>
  // Contains no secrets, only deployment metadata.
  const buildScript = `<script>window.CARNAVAL_BUILD={version:"${appVersion}",gitSha:"${gitSha}",buildId:"${buildId}",buildTime:"${buildTime}",environment:"${environment}",apiContract:${apiContract}};</script>`;
  html = html.replace('</head>', buildScript + '\n</head>');

  // ── 4b. Add ?v=<gitSha> to all local JS/CSS asset URLs ──
  // This changes the URL on every new deployment, forcing Telegram WebView
  // to bypass its HTTP cache and fetch fresh assets.
  // Only replaces LOCAL paths (starting with /) — NOT external https:// URLs.
  html = html.replace(/((?:src|href)=")(\/(js|css)\/[^"?]+\.(?:js|css))(")/g, `$1$2?v=${gitSha}$4`);
  // Handle single-quote variants
  html = html.replace(/((?:src|href)=')(\/(js|css)\/[^'?]+\.(?:js|css))(')/g, `$1$2?v=${gitSha}$4`);

  writeFileSync(indexPath, html);
  console.log(`[Vercel Build] Injected window.CARNAVAL_BUILD into index.html (gitSha=${gitSha})`);
  console.log(`[Vercel Build] Added ?v=${gitSha} cache-busting to all local JS/CSS asset URLs`);

  const buildOutputConfig = {
    version: 3,
    routes: [
      {
        src: '^/api/(.*)$',
        dest: `${backendOrigin}/api/$1`,
        headers: {
          'cache-control': 'no-store, no-cache, must-revalidate',
        },
      },
      {
        handle: 'filesystem',
      },
      {
        src: '^/(.*)$',
        dest: '/index.html',
      },
    ],
  };

  writeFileSync(
    join(VERCEL_OUTPUT_DIR, 'config.json'),
    JSON.stringify(buildOutputConfig, null, 2) + '\n'
  );
  console.log('[Vercel Build] .vercel/output Build Output API v3 created.');
} catch (err) {
  console.warn('[Vercel Build] Notice: .vercel/output creation skipped or completed:', err.message);
}

console.log('[Vercel Build] Build finished successfully.');
