// ets-loader-hooks - Node 模块钩子：把 .ets 按 TypeScript 处理（只擦类型，不改语义）
//
// 鸿蒙 .ets 的非 UI 纯逻辑（libs/protocol、libs/chat 等）是合法 TS 的子集，
// 这里用 Node 内置 stripTypeScriptTypes 擦类型后按 ESM 装载——单测直跑 .ets 源码，
// 不引入第三方转译器（仓内既有形态之外不加依赖）。

import { stripTypeScriptTypes } from 'node:module';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

export async function resolve(specifier, context, nextResolve) {
  try {
    return await nextResolve(specifier, context);
  } catch (e) {
    // 仓内 .ets 互导惯例不带扩展名（ohosTest 同款）：相对引用补 .ets 再试
    if (specifier.startsWith('.') || specifier.startsWith('/')) {
      return await nextResolve(specifier + '.ets', context);
    }
    throw e;
  }
}

export async function load(url, context, nextLoad) {
  if (url.endsWith('.ets')) {
    const filePath = fileURLToPath(url);
    const source = readFileSync(filePath, 'utf8');
    const stripped = stripTypeScriptTypes(source, { mode: 'strip' });
    return { format: 'module', source: stripped, shortCircuit: true };
  }
  return nextLoad(url, context);
}
