"""分析 pylint 报告 JSON，抽样打印 broad-exception-caught / wrong-import-position / undefined-variable。"""
import json

with open('audit-reports/pylint-report-v4.json', 'r') as f:
    data = json.load(f)

# Analyze broad-exception-caught
broad = [item for item in data if item['symbol'] == 'broad-exception-caught']
print('=== broad-exception-caught sample locations ===')
for item in broad[:10]:
    print(f"  {item['path']}:{item['line']}")

# Analyze wrong-import-position
wrong_import = [item for item in data if item['symbol'] == 'wrong-import-position']
print('\n=== wrong-import-position sample locations ===')
for item in wrong_import[:10]:
    print(f"  {item['path']}:{item['line']}")

# Analyze undefined-variable
undefined = [item for item in data if item['symbol'] == 'undefined-variable']
print('\n=== undefined-variable sample locations ===')
for item in undefined[:10]:
    print(f"  {item['path']}:{item['line']} - {item['message']}")
