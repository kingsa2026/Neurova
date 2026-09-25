#!/usr/bin/env node
/**
 * Neurova Pinia Store Deployment Script
 * 
 * This script automates the deployment of optimized Pinia stores:
 * 1. Backup existing files
 * 2. Deploy optimized versions
 * 3. Run TypeScript type check
 * 4. Run unit tests
 * 5. Generate report
 */

const fs = require('fs')
const path = require('path')
const { execSync } = require('child_process')

// Colors for console output
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

function step(message) {
  log(`\n📍 ${message}`, 'cyan')
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

// Configuration
const STORES = ['chat', 'agents', 'collaboration', 'messageQueue']
const BASE_DIR = path.join(__dirname, 'NeurUI', 'src', 'stores')
const BACKUP_DIR = path.join(__dirname, 'backups', `neurui-stores-${new Date().toISOString().slice(0, 10)}`)

// Step 1: Create backup directory
function createBackupDirectory() {
  step('Creating backup directory...')
  
  try {
    if (!fs.existsSync(BACKUP_DIR)) {
      fs.mkdirSync(BACKUP_DIR, { recursive: true })
      success(`Backup directory created: ${BACKUP_DIR}`)
    } else {
      warning(`Backup directory already exists: ${BACKUP_DIR}`)
    }
  } catch (err) {
    error(`Failed to create backup directory: ${err.message}`)
    process.exit(1)
  }
}

// Step 2: Backup and deploy each store
function deployStores() {
  step('Deploying optimized stores...')
  
  let deployedCount = 0
  
  for (const storeName of STORES) {
    const originalPath = path.join(BASE_DIR, `${storeName}.ts`)
    const optimizedPath = path.join(BASE_DIR, `${storeName}.optimized.ts`)
    const backupPath = path.join(BACKUP_DIR, `${storeName}.ts`)
    
    log(`\nProcessing ${storeName}...`)
    
    // Check if optimized version exists
    if (!fs.existsSync(optimizedPath)) {
      warning(`Optimized version not found: ${optimizedPath}`)
      continue
    }
    
    // Backup original if it exists
    if (fs.existsSync(originalPath)) {
      try {
        fs.copyFileSync(originalPath, backupPath)
        success(`Backed up: ${originalPath} → ${backupPath}`)
      } catch (err) {
        error(`Failed to backup ${storeName}: ${err.message}`)
        continue
      }
    }
    
    // Replace with optimized version
    try {
      if (fs.existsSync(originalPath)) {
        fs.unlinkSync(originalPath)
      }
      fs.renameSync(optimizedPath, originalPath)
      success(`Deployed: ${storeName}.ts`)
      deployedCount++
    } catch (err) {
      error(`Failed to deploy ${storeName}: ${err.message}`)
    }
  }
  
  success(`Deployment complete: ${deployedCount}/${STORES.length} stores deployed`)
  return deployedCount
}

// Step 3: Run TypeScript type check
async function runTypeCheck() {
  step('Running TypeScript type check...')
  
  try {
    const result = execSync('cd NeurUI && npx vue-tsc --noEmit', {
      encoding: 'utf-8',
      stdio: 'pipe'
    })
    
    success('TypeScript type check passed')
    return true
  } catch (err) {
    error('TypeScript type check failed')
    console.error(err.stdout?.toString())
    return false
  }
}

// Step 4: Run unit tests
async function runTests() {
  step('Running unit tests...')
  
  try {
    const result = execSync('cd NeurUI && npm run test -- --run', {
      encoding: 'utf-8',
      stdio: 'inherit'
    })
    
    success('All tests passed')
    return true
  } catch (err) {
    error('Some tests failed')
    return false
  }
}

// Step 5: Generate deployment report
function generateReport(deployedCount, typeCheckPassed, testsPassed) {
  step('Generating deployment report...')
  
  const report = `
# Deployment Report

**Date**: ${new Date().toLocaleString()}
**Status**: ${deployedCount === STORES.length ? '✅ Success' : '⚠️  Partial'}

## Summary

- **Stores Deployed**: ${deployedCount}/${STORES.length}
- **TypeScript Check**: ${typeCheckPassed ? '✅ Passed' : '❌ Failed'}
- **Unit Tests**: ${testsPassed ? '✅ Passed' : '❌ Failed'}

## Deployed Files

${STORES.map(s => `- ${s}.ts`).join('\n')}

## Backup Location

${BACKUP_DIR}

## Next Steps

1. Verify application functionality
2. Run integration tests
3. Monitor for any issues
4. Deploy to production if all checks pass

## Rollback Instructions

If issues are encountered, restore from backup:

\`\`\`bash
cd ${BACKUP_DIR}
for file in *.ts; do
  cp "$file" "../NeurUI/src/stores/$file"
done
\`\`\`
`;

  const reportPath = path.join(__dirname, 'DEPLOYMENT_REPORT.md')
  fs.writeFileSync(reportPath, report)
  
  success(`Report generated: ${reportPath}`)
}

// Main execution
async function main() {
  log('\n🚀 Neurova Pinia Store Deployment\n', 'cyan')
  
  try {
    // Step 1: Create backup directory
    createBackupDirectory()
    
    // Step 2: Deploy stores
    const deployedCount = deployStores()
    
    if (deployedCount === 0) {
      error('No stores were deployed. Exiting.')
      process.exit(1)
    }
    
    // Step 3: Type check
    const typeCheckPassed = await runTypeCheck()
    
    // Step 4: Run tests
    const testsPassed = await runTests()
    
    // Step 5: Generate report
    generateReport(deployedCount, typeCheckPassed, testsPassed)
    
    // Final summary
    log('\n\n🎉 Deployment Complete!\n', typeCheckPassed && testsPassed ? 'green' : 'yellow')
    log(`Status: ${typeCheckPassed && testsPassed ? '✅ All checks passed' : '⚠️  Some checks failed'}`, typeCheckPassed && testsPassed ? 'green' : 'yellow')
    log(`Backup location: ${BACKUP_DIR}`, 'cyan')
    
  } catch (err) {
    error(`Deployment failed: ${err.message}`)
    process.exit(1)
  }
}

// Run deployment
main()
