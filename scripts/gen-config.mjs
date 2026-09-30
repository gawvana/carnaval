#!/usr/bin/env node
/**
 * scripts/gen-config.mjs — генерация runtime-config.js при сборке на Vercel.
 *
 * Читает переменную окружения CARNAVAL_API_URL и генерирует
 * carnaval/web/js/runtime-config.js с базовым адресом бэкенда.
 * Если переменная отсутствует — сборка падает с ошибкой.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');

const apiUrl = process.env.CARNAVAL_API_URL;

if (!apiUrl || !apiUrl.trim()) {
  console.error('\n❌ ОШИБКА СБОРКИ VERCEL:');
  console.error('Переменная окружения CARNAVAL_API_URL не задана!');
  console.error('Укажите HTTPS адрес бэкенда Cardinal в Vercel Dashboard:');
  console.error('  Settings -> Environment Variables -> CARNAVAL_API_URL');
  console.error('  Пример: https://your-backend.infrlo.app\n');
  process.exit(1);
}

const cleanUrl = apiUrl.trim().replace(/\/+$/, '');
const targetDir = path.join(rootDir, 'carnaval', 'web', 'js');
const targetFile = path.join(targetDir, 'runtime-config.js');

const content = `// Автоматически сгенерировано при сборке Vercel
window.__CARNAVAL_API = ${JSON.stringify(cleanUrl)};
`;

fs.mkdirSync(targetDir, { recursive: true });
fs.writeFileSync(targetFile, content, 'utf8');

console.log(`✅ runtime-config.js успешно создан: API URL = ${cleanUrl}`);
