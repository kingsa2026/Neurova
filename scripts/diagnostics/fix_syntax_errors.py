"""一次性修复脚本：修复指定文件清单中的 logger 格式化语法错误。"""
import os
import re
from pathlib import Path

files_to_fix = [
    'neurova/post_chat_pipeline.py',
    'neurova/agent/memory_retrieval_chain.py',
    'neurova/api/app.py',
    'neurova/channels/qclaw_service.py',
    'neurova/cognitive_layers/emotion_context_layer/emotion_hub_engine.py',
    'neurova/cognitive_layers/growth_layer/analyzer.py',
    'neurova/cognitive_layers/memory_layer/enhanced_retrieval.py',
    'neurova/cognitive_layers/memory_layer/modules/sleep_module.py',
    'neurova/core/cognition_orchestrator.py',
    'neurova/core/intrinsic_motivation.py',
    'neurova/core/startup_manager.py',
    'neurova/core/trace_recorder.py',
    'neurova/evolution/genetic_engine.py',
    'neurova/recovery/shutdown_guard.py',
    'neurova/skills/hub_client.py',
    'neurova/skills/prompt_optimizer.py',
    'neurova/tts/mock_tts_simple.py',
]

for filepath in files_to_fix:
    if not os.path.exists(filepath):
        continue
    
    try:
        content = Path(filepath).read_text(encoding='utf-8')
    except Exception:
        continue
    
    # Fix pattern: variable:.2f in logger calls
    lines = content.split('\n')
    new_lines = []
    changed = False
    
    for line in lines:
        if 'logger.' in line and re.search(r'\w+:\.\d+f', line):
            # Find the format spec
            format_match = re.search(r':(\.\d+f)', line)
            if format_match:
                precision = format_match.group(1)
                # Remove :<precision> from variable
                new_line = re.sub(r',\s*(\w+):\.\d+f\)', r', \1)', line)
                # Replace first %s with %<precision>
                new_line = new_line.replace('%s', f'%{precision}', 1)
                if new_line != line:
                    line = new_line
                    changed = True
        new_lines.append(line)
    
    if changed:
        Path(filepath).write_text('\n'.join(new_lines), encoding='utf-8')
        print(f'Fixed: {filepath}')

print('Done')
