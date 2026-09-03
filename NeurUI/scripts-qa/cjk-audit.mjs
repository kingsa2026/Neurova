import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
function walk(dir) {
  const out = [];
  for (const f of readdirSync(dir)) {
    if (f.startsWith('.')) continue;
    const p = join(dir, f);
    if (statSync(p).isDirectory()) out.push(...walk(p));
    else if (/\.(vue|ts)$/.test(f)) out.push(p);
  }
  return out;
}
const cjk = /[\u4e00-\u9fff]/;
const hits = [];
for (const file of walk('src')) {
  if (file.includes('i18n')) continue;
  if (file.includes('__tests__')) continue;
  if (file.includes('node_modules')) continue;
  const code = readFileSync(file, 'utf8');
  if (!cjk.test(code)) continue;
  for (const [i, line] of code.split('\n').entries()) {
    if (cjk.test(line)) hits.push(`${file}:${i + 1}: ${line.trim().slice(0, 110)}`);
  }
}
console.log('total hits:', hits.length);
for (const h of hits.slice(0, 120)) console.log(h);
