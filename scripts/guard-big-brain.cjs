#!/usr/bin/env node
/**
 * Neurova LLM Cost Control - Big-brain Model Guard
 * 
 * Purpose: Prevent expensive models from being used in non-critical paths
 * 
 * Rules:
 * 1. Expensive models (gpt-4, claude-3-opus, etc.) only allowed in agent turns
 * 2. Small models required for triage, embedding, validation
 * 3. CI-enforced: Must pass before merge
 * 
 * Usage:
 *   npm run guard:big-brain
 *   node scripts/guard-big-brain.js [file-path]
 */

const fs = require('fs')
const path = require('path')

// Colors
const colors = {
  reset: '\x1b[0m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  red: '\x1b[31m',
  blue: '\x1b[34m',
  cyan: '\x1b[36m',
}

function log(message, color = 'reset') {
  console.log(`${colors[color]}${message}${colors.reset}`)
}

function success(message) {
  log(`✅ ${message}`, 'green')
}

function warning(message) {
  log(`⚠️  ${message}`, 'yellow')
}

function error(message) {
  log(`❌ ${message}`, 'red')
}

// ============================================================================
// Configuration
// ============================================================================

// Expensive models that should only be used in critical paths
const EXPENSIVE_MODELS = [
  'gpt-4', 'gpt-4-turbo', 'gpt-4o', 'gpt-4o-mini',
  'claude-3-opus', 'claude-3-sonnet', 'claude-3-haiku', 'claude-3.5-sonnet',
  'gemini-1.5-pro', 'gemini-exp',
  'claude-2', 'claude-instant',
]

// Allowed contexts for expensive models
const ALLOWED_CONTEXTS = [
  'agent_turn',
  'agent_response',
  'summarization',
  'complex_reasoning',
]

// Forbidden contexts (should use small models like gpt-3.5-turbo, claude-haiku)
const FORBIDDEN_CONTEXTS = [
  'triage',
  'classification',
  'embedding',
  'vector_search',
  'metadata',
  'validation',
  'filtering',
  'preprocessing',
  'postprocessing',
]

// Patterns to detect context in code
const CONTEXT_PATTERNS = {
  forbidden: [
    /@track_llm_call\(.*provider.*model.*\)/,  // Decorator usage
    /client\.chat\.completions\.create/,        // OpenAI API call
    /anthropic\.messages\.create/,              // Claude API call
    /google\.genai/,                            // Gemini API call
    /ollama\.chat/,                             // Ollama API call
    /llm_client\.call/,                         // Neurova LLM client
  ],
  context_identifiers: [
    /def\s+(triage|classify|embed|validate|filter|preprocess|postprocess)/,
    /class\s*(Triage|Classifier|Embedder|Validator)/,
  ],
  // Exclude price table definitions (not actual LLM calls)
  exclude_patterns: [
    /PRICE_TABLE\s*=\s*{/,           // Price table definition
    /price_map\s*=\s*{/,             // Price map definition
    /PRICING\s*=\s*{/,               // Pricing config
  ]
}

// ============================================================================
// Core Logic
// ============================================================================

/**
 * Check if a file uses expensive models in forbidden contexts
 */
function checkFile(filePath) {
  const content = fs.readFileSync(filePath, 'utf-8')
  const lines = content.split('\n')
  
  const violations = []
  let currentContext = null
  
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const lineNumber = i + 1
    
    // Skip price table definitions (not actual LLM calls)
    if (CONTEXT_PATTERNS.exclude_patterns.some(pattern => pattern.test(line))) {
      continue
    }
    
    // Detect context changes
    for (const pattern of CONTEXT_PATTERNS.context_identifiers) {
      const match = line.match(pattern)
      if (match) {
        currentContext = match[1]?.toLowerCase() || 'unknown'
        break
      }
    }
    
    // Check for expensive model usage
    for (const model of EXPENSIVE_MODELS) {
      if (line.includes(model)) {
        // Only flag as violation if we're in a forbidden context AND there's an actual API call pattern nearby
        const isForbiddenContext = FORBIDDEN_CONTEXTS.some(ctx => 
          currentContext?.includes(ctx) || line.toLowerCase().includes(ctx)
        )
        
        const isAllowedContext = ALLOWED_CONTEXTS.some(ctx => 
          currentContext?.includes(ctx) || line.toLowerCase().includes(ctx)
        )
        
        // Check if this line contains an actual LLM API call (not just config)
        const hasApiCall = CONTEXT_PATTERNS.forbidden.some(pattern => pattern.test(line))
        
        // Skip if it's just a price table or configuration
        const isConfigLine = CONTEXT_PATTERNS.exclude_patterns.some(pattern => pattern.test(line))
        
        if (isForbiddenContext && !isAllowedContext && hasApiCall && !isConfigLine) {
          violations.push({
            line: lineNumber,
            model: model,
            context: currentContext || 'unknown',
            code: line.trim(),
          })
        }
      }
    }
  }
  
  return violations
}

/**
 * Recursively find all Python files under a directory, or return the
 * single file if the target is itself a .py file (the CLI contract in the
 * usage header advertises `[file-path]`, so honor it here).
 */
function findPythonFiles(dir, excludeDirs = ['node_modules', '__pycache__', '.venv']) {
  const stat = fs.statSync(dir)
  if (stat.isFile()) {
    return dir.endsWith('.py') ? [dir] : []
  }

  const files = []
  const entries = fs.readdirSync(dir, { withFileTypes: true })
  
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name)
    
    if (entry.isDirectory()) {
      if (!excludeDirs.includes(entry.name)) {
        files.push(...findPythonFiles(fullPath, excludeDirs))
      }
    } else if (entry.isFile() && entry.name.endsWith('.py')) {
      files.push(fullPath)
    }
  }
  
  return files
}

/**
 * Main check function
 */
function runCheck(targetPath = null) {
  log('\n🔍 Starting Big-brain Model Guard Check\n', 'cyan')
  
  // Determine target path
  const searchPath = targetPath || 'neurova'
  
  if (!fs.existsSync(searchPath)) {
    error(`Path not found: ${searchPath}`)
    process.exit(1)
  }
  
  // Find all Python files
  log(`📂 Scanning directory: ${searchPath}`)
  const pythonFiles = findPythonFiles(searchPath)
  log(`📄 Found ${pythonFiles.length} Python files`)
  
  // Check each file
  let totalViolations = 0
  const allViolations = []
  
  for (const filePath of pythonFiles) {
    const violations = checkFile(filePath)
    
    if (violations.length > 0) {
      allViolations.push({
        file: filePath,
        violations: violations,
      })
      totalViolations += violations.length
    }
  }
  
  // Report results
  log('\n' + '='.repeat(80), 'cyan')
  
  if (totalViolations === 0) {
    success('✅ No violations found! All expensive models are used appropriately.')
    log('\n💡 Tip: Consider using smaller models for triage, classification, etc.\n', 'green')
    return 0
  }
  
  error(`❌ Found ${totalViolations} violation(s)!`)
  log('\n📋 Violation Details:\n')
  
  for (const { file, violations } of allViolations) {
    log(`\n📄 ${file}`, 'yellow')
    
    for (const v of violations) {
      log(`   Line ${v.line}: Using "${v.model}" in "${v.context}" context`, 'red')
      log(`   Code: ${v.code}`, 'red')
      log(`   → Should use small model (gpt-3.5-turbo, claude-haiku)\n`, 'red')
    }
  }
  
  log('\n' + '='.repeat(80), 'cyan')
  error('💥 Big-brain model guard FAILED!\n')
  log('📖 Fix guidelines:', 'yellow')
  log('  1. Use small models for triage, classification, validation', 'yellow')
  log('  2. Reserve expensive models for agent turns only', 'yellow')
  log('  3. Run "npm run guard:big-brain" again after fixing', 'yellow')
  log('')
  
  return 1
}

// ============================================================================
// CLI Entry Point
// ============================================================================

function main() {
  const args = process.argv.slice(2)
  const targetPath = args[0] || null
  
  const exitCode = runCheck(targetPath)
  process.exit(exitCode)
}

main()
