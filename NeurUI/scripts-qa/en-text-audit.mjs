import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
function walk(dir) {
  const out = [];
  for (const f of readdirSync(dir)) {
    if (f.startsWith('.')) continue;
    const p = join(dir, f);
    if (statSync(p).isDirectory()) out.push(...walk(p));
    else if (/\.(vue)$/.test(f)) out.push(p);
  }
  return out;
}
const hits = [];
for (const file of walk('src')) {
  if (file.includes('__tests__')) continue;
  const code = readFileSync(file, 'utf8');
  for (const [i, line] of code.split('\n').entries()) {
    // text node like: >Some Words<
    const m = line.match(/>\s*([A-Za-z][A-Za-z0-9 ,"'\-:&().!/+]{2,})\s*</);
    if (m && !/\{\{|\$t\b|^\s*<!--|-->\s*$/.test(line)) {
      hits.push(`${file}:${i + 1}: >${m[1].trim()}<`);
    }
    // attribute-only strings hardcoded in template props are separate
  }
}
console.log('template en text nodes:', hits.length);
for (const h of hits.slice(0, 120)) console.log(h);
