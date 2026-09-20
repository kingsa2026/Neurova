#!/usr/bin/env node
/**
 * Neurova LLM Cost Control - Tracking Guard
 * 
 * Purpose: Ensure all LLM API calls are decorated with @track_llm_call
 * 
 * Rules:
 * 1. All LLM API calls must use cost tracking decorator
 * 2. No bare LLM API calls allowed without tracking
 * 3. CI-enforced: Must pass before merge
 * 
 * Usage:
 *   npm run guard:llm-tracked
 *   node scripts/guard-llm-tracked.cjs [file-path]
 */

const fs = require('fs')
const path = require('path')

// Colors
const colors = {
  reset: '\x1b[0m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  red: '\x1b[31m',
  blue: '\x1b:34m',
  cyan: '\x1b:36m',
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

// LLM API call patterns to detect
const LLM_API_PATTERNS = [
  // OpenAI
  /client\.chat\.completions\.create/,
  /openai\.ChatCompletion/,
  /await.*\.createCompletion/,
  
  // Anthropic Claude
  /anthropic\.messages\.create/,
  /claude\.messages\.create/,
  /await.*\.claude\.chat/,
  
  // Google Gemini
  /google\.genai/,
  /gemini\.models\.generateContent/,
  /await.*\.gemini\.generate/,
  
  // Ollama
  /ollama\.chat/,
  /ollama\.generate/,
  
  // Neurova custom
  /llm_client\.call/,
  /provider\.call_llm/,
]

// Decorator patterns (should be present before function definition)
const DECORATOR_PATTERNS = [
  /@track_llm_call\(/,
  /@cost_tracking\(/,
  /@log_llm_call\(/,
]

// In-body tracking call patterns: streaming generators cannot use a
// return-intercepting decorator, so they call record_llm_cost(...) explicitly
// inside the function body. A function containing one of these is tracked.
const TRACKING_CALL_PATTERNS = [
  /\brecord_llm_cost\s*\(/,
  /\bCostTracker\s*\(/,
]

// Context where decorators might be defined (to avoid false positives)
const EXCLUDED_CONTEXTS = [
  /def\s+(mock_|fake_|stub_|dummy_)/,  // Mock functions
  /class\s*(Mock|Fake|Stub|Dummy)/,    // Mock classes
  /#.*tracking.*disabled/,              // Comments about disabling tracking
  /if\s+DEBUG/,                         // Debug mode code
]

// Files to exclude from tracking check (capability probing, tests)
const EXCLUDED_FILES = [
  /capability_detector\.py$/,          // Model capability detection
]

// ============================================================================
// Core Logic
// ============================================================================

/**
 * Check if a line is inside an excluded function definition
 */
function isInExcludedContext(lines, lineNumber, maxLinesBack = 50) {
  const start = Math.max(0, lineNumber - maxLinesBack)
  
  for (let i = lineNumber - 1; i >= start; i--) {
    const line = lines[i]
    
    // Found function/class definition
    const funcMatch = line.match(/^(async\s+)?def\s+([\w_]+)/)
    if (funcMatch) {
      const funcName = funcMatch[2]
      // Check if function name matches excluded patterns
      return EXCLUDED_CONTEXTS.some(pattern => pattern.test(funcName))
    }
  }
  
  return false
}

/**
 * Scan a function's body (forward from its def line) for an explicit
 * tracking call. Used to credit streaming generators that record cost
 * in-body rather than via a decorator.
 */
function bodyHasTrackingCall(lines, defIndex, maxLines = 500) {
  const defIndent = (lines[defIndex].match(/^(\s*)/) || ['', ''])[1].length
  for (let k = defIndex + 1; k < lines.length && k < defIndex + maxLines; k++) {
    const l = lines[k]
    if (l.trim() === '') {
      continue
    }
    const ind = (l.match(/^(\s*)/) || ['', ''])[1].length
    if (ind <= defIndent) {
      break // left the function body
    }
    if (TRACKING_CALL_PATTERNS.some(pattern => pattern.test(l))) {
      return true
    }
  }
  return false
}

/**
 * Check if a line is inside a function/class definition
 */
function isInsideDefinition(lines, lineNumber, maxLinesBack = 50) {
  const start = Math.max(0, lineNumber - maxLinesBack)
  
  for (let i = lineNumber - 1; i >= start; i--) {
    const line = lines[i]
    
    // Found decorator
    if (DECORATOR_PATTERNS.some(pattern => pattern.test(line))) {
      return true
    }
    
    // Found function/class definition. The tracking decorator may sit on
    // the line(s) directly above it (especially for module-level defs that
    // are not indented), so inspect the decorator stack above the def
    // before deciding.
    if (/^\s*(async\s+)?def\s+\w+|\bclass\b/.test(line)) {
      // Decorators may span multiple lines (@track_llm_call(\n  arg\n  )).
      // Scan a bounded window above the def for any tracking decorator,
      // stopping at a preceding def/class so we never cross into the
      // previous function.
      const scanStart = Math.max(0, i - 12)
      for (let j = i - 1; j >= scanStart; j--) {
        if (/^\s*(async\s+)?def\s+\w+|\bclass\b/.test(lines[j])) {
          break
        }
        if (DECORATOR_PATTERNS.some(pattern => pattern.test(lines[j]))) {
          return true
        }
      }
      // No decorator above the def: still tracked if the function body
      // records cost explicitly (streaming generators).
      return bodyHasTrackingCall(lines, i)
    }
    
    // Reached another decorator or end of relevant section
    if (/^@(?!track_llm_call)/.test(line)) {
      return false
    }
  }
  
  return false
}

/**
 * Check if a file has LLM API calls without tracking decorators
 */
function checkFile(filePath) {
  // Skip excluded files
  if (EXCLUDED_FILES.some(pattern => pattern.test(filePath))) {
    console.log(`⏭️  Skipping excluded file: ${filePath}`)
    return []
  }
  
  const content = fs.readFileSync(filePath, 'utf-8')
  const lines = content.split('\n')
  
  const violations = []
  
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const lineNumber = i + 1
    
    // Skip excluded contexts
    if (EXCLUDED_CONTEXTS.some(pattern => pattern.test(line))) {
      continue
    }
    
    // Check for LLM API calls
    for (const pattern of LLM_API_PATTERNS) {
      if (pattern.test(line)) {
        // Skip if inside excluded context (e.g., _probe_, test_)
        if (isInExcludedContext(lines, i)) {
          break
        }
        
        // Check if there's a decorator above this line
        const hasDecorator = isInsideDefinition(lines, i)
        
        if (!hasDecorator) {
          violations.push({
            line: lineNumber,
            apiCall: line.trim().substring(0, 80),
            context: extractContext(lines, i),
          })
        }
        
        break // Only report once per line even if multiple patterns match
      }
    }
  }
  
  return violations
}

/**
 * Extract context around the violation
 */
function extractContext(lines, lineNumber, contextSize = 3) {
  const start = Math.max(0, lineNumber - contextSize)
  const end = Math.min(lines.length, lineNumber + contextSize + 1)
  
  return lines.slice(start, end).join('\n').trim()
}

/**
 * Recursively find all Python files under a directory, or return the
 * single file if the target is itself a .py file (honor the `[file-path]`
 * CLI contract advertised in the usage header).
 */
function findPythonFiles(dir, excludeDirs = ['node_modules', '__pycache__', '.venv', 'tests']) {
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
  log('\n🔍 Starting LLM Tracking Guard Check\n', 'cyan')
  
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
    success('✅ No violations found! All LLM calls are properly tracked.')
    log('\n💡 Tip: Ensure all new LLM API calls use @track_llm_call decorator.\n', 'green')
    return 0
  }
  
  error(`❌ Found ${totalViolations} violation(s)!`)
  log('\n📋 Violation Details:\n')
  
  for (const { file, violations } of allViolations) {
    log(`\n📄 ${file}`, 'yellow')
    
    for (const v of violations) {
      log(`   Line ${v.line}: Untracked LLM API call`, 'red')
      log(`   Code: ${v.apiCall}`, 'red')
      log(`   → Add @track_llm_call decorator`, 'red')
      
      // Show context
      if (v.context) {
        log(`   Context:\n${v.context.split('\n').map(l => '     ' + l).join('\n')}`, 'yellow')
      }
      
      log('')
    }
  }
  
  log('\n' + '='.repeat(80), 'cyan')
  error('💥 LLM tracking guard FAILED!\n')
  log('📖 Fix guidelines:', 'yellow')
  log('  1. Add @track_llm_call decorator to all LLM API calls', 'yellow')
  log('  2. Example:', 'yellow')
  log('     @track_llm_call(provider=LLMProvider.OPENAI, model="gpt-3.5-turbo", agent_id="default")', 'yellow')
  log('     async def call_llm(messages):', 'yellow')
  log('         response = await client.chat.completions.create(...)  # This will be tracked', 'yellow')
  log('')
  log('  3. Run "npm run guard:llm-tracked" again after fixing', 'yellow')
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
