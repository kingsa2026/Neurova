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

export interface DuplicateFunctionScanOptions {
  suffixes: string[]
  includeTestDirs: boolean
  includeTestFiles: boolean
}

export interface DuplicateFunctionCaliberCandidate {
  key: string
  label: string
  roots: string[]
  options: DuplicateFunctionScanOptions
}

export interface DuplicateFunctionCaliberReading {
  key: string
  label: string
  crossFileSameNames: number
}

export interface DuplicateFunctionCounts {
  sameBodyGroups: number
  variantBodyGroups: number
  tierAGroups: number
  crossFileUniqueNames: number
  overlappingNames: string[]
  scannedFiles: number
}

export declare const SCAN_SUFFIXES: string[]
export declare const SCAN_ROOT_LABEL: string
export declare const LEDGER_BEGIN: string
export declare const LEDGER_END: string
export declare const CALIBER_BEGIN: string
export declare const CALIBER_END: string
export declare const DEFAULT_SCAN_OPTIONS: DuplicateFunctionScanOptions
export declare const CALIBER_CANDIDATES: DuplicateFunctionCaliberCandidate[]
export declare const LOCAL_COUPLING_PATTERNS: Array<{ name: string; pattern: RegExp }>
export declare function collectSourceFiles(
  dir?: string,
  out?: string[],
  options?: DuplicateFunctionScanOptions,
): string[]
export declare function collectDefinitions(files?: string[]): Map<string, Array<{ relPath: string; line: number; body: string }>>
export declare function auditDuplicateFunctions(): DuplicateFunctionReport
export declare function caliberSummary(): Record<string, unknown>
export declare function countCrossFileNames(candidate: DuplicateFunctionCaliberCandidate, rootDir?: string): number
export declare function caliberCandidates(): DuplicateFunctionCaliberReading[]
export declare function reportCounts(report?: DuplicateFunctionReport): DuplicateFunctionCounts
export declare function renderCaliberBlock(report?: DuplicateFunctionReport): string
export declare function inventoryPayload(report?: DuplicateFunctionReport): DuplicateFunctionInventory
export declare function renderLedgerBlock(report?: DuplicateFunctionReport): string
