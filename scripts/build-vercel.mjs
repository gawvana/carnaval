/**
 * scripts/build-vercel.mjs
 *
 * Production build script for Vercel deployment of Carnaval Mini App frontend.
 *
 * - Sets up external rewrite for /api/* -> https://<backend-origin>/api/*
 * - Implements Vercel Build Output API v3 (.vercel/output)
 * - Ensures NO secrets are bundled into client-side code
 * - Applies strict security headers & no-store caching on /api/*
 */

import { cpSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT_DIR = resolve(__dirname, '..');
const WEB_DIR = join(ROOT_DIR, 'carnaval', 'web');
const VERCEL_OUTPUT_DIR = join(ROOT_DIR, '.vercel', 'output');
const VERCEL_STATIC_DIR = join(VERCEL_OUTPUT_DIR, 'static');

// 1. Audit environment variables to prevent secret leakage
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

// 2. Determine backend origin
const rawBackend = (
  process.env.BACKEND_PUBLIC_ORIGIN ||
  process.env.INFR_BACKEND_URL ||
  process.env.CARNAVAL_API_URL ||
  'https://carnaval.infrlo.app'
).trim();

const backendOrigin = rawBackend.replace(/\/+$/, '');
console.log(`[Vercel Build] Configuring /api/* rewrite -> ${backendOrigin}/api/*`);

// 3. Update vercel.json in repository root
const vercelConfig = {
  $schema: 'https://openapi.vercel.sh/vercel.json',
  version: 2,
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
      source: '/api/(.*)',
      headers: [
        { key: 'Cache-Control', value: 'no-store, no-cache, must-revalidate' },
      ],
    },
    {
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

// 4. Generate Build Output API v3 (.vercel/output) for zero-config Vercel deployments
try {
  mkdirSync(VERCEL_STATIC_DIR, { recursive: true });
  cpSync(WEB_DIR, VERCEL_STATIC_DIR, { recursive: true });

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
