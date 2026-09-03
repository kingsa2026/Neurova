import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

const srcRoot = 'src';
const localeDir = join(srcRoot, 'i18n', 'locales');

function walk(dir) {
  const out = [];
  for (const f of readdirSync(dir)) {
    if (f.startsWith('.')) continue;
    const p = join(dir, f);
    if (statSync(p).isDirectory()) out.push(...walk(p));
    else if (/\.(vue|ts|js)$/.test(f)) out.push(p);
  }
  return out;
}

// Load STORE_CANVAS from _canvasStores.ts
const storesCode = readFileSync(join(localeDir, '_canvasStores.ts'), 'utf8');
const entriesStart = storesCode.indexOf('= [') + 3;
const entriesEnd = storesCode.indexOf('export const STORE_CANVAS');
let entriesBody = storesCode.slice(entriesStart, entriesEnd).trim();
entriesBody = entriesBody.replace(/\]\s*$/, '').replace(/,\s*$/, '');
let STORE_CANVAS = {};
try {
  const arr = Function('"use strict"; return [' + entriesBody + '];')();
  STORE_CANVAS = Object.fromEntries(arr);
} catch (e) {
  console.error('STORE_CANVAS load failed:', e.message.slice(0, 120));
}

function loadLocale(file) {
  let code = readFileSync(file, 'utf8');
  code = code.replace(/import\s*\{[^}]*\}\s*from\s*['"]\.\/_canvasStores['"]\s*/g, '');
  code = code.replace(/as const/g, '');
  const m = code.match(/export\s+default\s+([\s\S]*)/);
  if (!m) throw new Error('no export default in ' + file);
  let body = m[1].trim().replace(/;+$/, '');
  const obj = Function('STORE_CANVAS', '"use strict"; return (' + body + ');')(STORE_CANVAS);
  return obj;
}

function flatten(obj, prefix = '') {
  const keys = [];
  for (const [k, v] of Object.entries(obj)) {
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      keys.push(...flatten(v, prefix ? `${prefix}.${k}` : k));
    } else {
      keys.push(prefix ? `${prefix}.${k}` : k);
    }
  }
  return keys;
}

const locales = {};
for (const f of readdirSync(localeDir)) {
  if (f.startsWith('_') || f.startsWith('.')) continue;
  const name = f.replace(/\.ts$/, '');
  try { locales[name] = flatten(loadLocale(join(localeDir, f))); }
  catch (e) { console.error('LOAD FAIL', name, e.message.slice(0, 100)); }
}

const zh = new Set(locales['zh-CN'] || []);
const en = new Set(locales['en-US'] || []);

const used = new Map();
for (const file of walk(srcRoot)) {
  const code = readFileSync(file, 'utf8');
  if (!code.includes('t(') && !code.includes('$t(')) continue;
  const re = /(?:^|[^A-Za-z0-9_$.])(?:\$)?t\s*\(\s*['"]([^'"]+)['"]/g;
  let m;
  while ((m = re.exec(code))) {
    const key = m[1];
    if (!used.has(key)) used.set(key, new Set());
    used.get(key).add(file);
  }
}

const MISSING_ZH = [], MISSING_EN = [], MISSING_OTHER = {};
for (const [key, files] of used) {
  if (!zh.has(key)) MISSING_ZH.push([key, [...files]]);
  if (!en.has(key)) MISSING_EN.push([key, [...files]]);
  for (const name of Object.keys(locales)) {
    if (name === 'zh-CN' || name === 'en-US') continue;
    if (!new Set(locales[name]).has(key)) { (MISSING_OTHER[name] ||= []).push(key); }
  }
}
console.log('=== zh-CN missing:', MISSING_ZH.length, '===');
for (const [k, f] of MISSING_ZH.slice(0, 80)) console.log('  ', k, ' <-- ', f[0]);
console.log('=== en-US missing:', MISSING_EN.length, '===');
for (const [k, f] of MISSING_EN.slice(0, 80)) console.log('  ', k, ' <-- ', f[0]);
console.log('=== other locales missing counts:', JSON.stringify(Object.fromEntries(Object.entries(MISSING_OTHER).map(([k,v])=>[k, v.length]))));
console.log('=== totals zh:', zh.size, 'en:', en.size, 'used:', used.size, '===');
