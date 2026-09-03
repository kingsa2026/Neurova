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
  if (file.includes('i18n') || file.includes('__tests__')) continue;
  const code = readFileSync(file, 'utf8');
  for (const [i, raw] of code.split('\n').entries()) {
    const line = raw.trim();
    if (!cjk.test(line)) continue;
    if (line.startsWith('//') || line.startsWith('*') || line.startsWith('/*') || line.startsWith('<!')) continue;
    // find CJK inside quotes
    const m = line.match(/(['"`])[^'"`\n]*[\u4e00-\u9fff][^'"`\n]*\1/);
    if (m) hits.push(`${file}:${i + 1}: ${line.slice(0, 120)}`);
  }
}
console.log('total literal hits:', hits.length);
for (const h of hits.slice(0, 200)) console.log(h);
