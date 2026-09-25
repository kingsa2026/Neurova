/**
 * `duplicate-function-audit.mjs` 的类型声明（供守卫测试按类型消费）。
 *
 * 口径说明见脚本头注释；此处只声明对外契约，实现事实源仍是 .mjs 本体。
 */
export interface DuplicateFunctionGroup {
  name: string
  sites: string[]
  body?: string
  coupling?: string[]
  variants?: number
  coupled?: boolean
}

export interface DuplicateFunctionReport {
  scannedFiles: number
  tiers: { A: DuplicateFunctionGroup[]; B: DuplicateFunctionGroup[]; C: DuplicateFunctionGroup[] }
}

export interface DuplicateFunctionLedgerEntry {
  name: string
  files: string[]
}

export interface DuplicateFunctionInventory {
  caliber: Record<string, unknown>
  scannedFiles: number
  tierA: DuplicateFunctionLedgerEntry[]
  tierB: DuplicateFunctionLedgerEntry[]
  tierC: DuplicateFunctionLedgerEntry[]
}

export declare const SCAN_SUFFIXES: string[]
export declare const SCAN_ROOT_LABEL: string
export declare const LEDGER_BEGIN: string
export declare const LEDGER_END: string
export declare const LOCAL_COUPLING_PATTERNS: Array<{ name: string; pattern: RegExp }>
export declare function collectSourceFiles(dir?: string, out?: string[]): string[]
export declare function collectDefinitions(files: string[]): Map<string, Array<{ relPath: string; line: number; body: string }>>
export declare function auditDuplicateFunctions(): DuplicateFunctionReport
export declare function caliberSummary(): Record<string, unknown>
export declare function inventoryPayload(report?: DuplicateFunctionReport): DuplicateFunctionInventory
export declare function renderLedgerBlock(report?: DuplicateFunctionReport): string
