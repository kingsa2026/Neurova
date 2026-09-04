"""Check initialization order in agent_core.py"""
import re
import sys

def check_init_order():
    with open('neurova/agent_core.py', 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # Find line numbers for key patterns
    evolution_init_line = None
    voice_bridge_init_line = None
    
    for i, line in enumerate(lines, 1):
        # Look for self.evolution = None or self.evolution = EvolutionOrchestrator()
        if re.search(r'self\.evolution\s*=\s*(None|EvolutionOrchestrator\(\))', line):
            evolution_init_line = i
        # Look for voice_memory_bridge initialization
        if 'voice_memory_bridge = VoiceMemoryBridge(' in line:
            voice_bridge_init_line = i
    
    print(f"self.evolution initialization line: {evolution_init_line}")
    print(f"voice_memory_bridge initialization line: {voice_bridge_init_line}")
    
    if evolution_init_line and voice_bridge_init_line:
        if evolution_init_line < voice_bridge_init_line:
            print("✅ PASS: self.evolution is initialized before voice_memory_bridge")
            return True
        else:
            print("❌ FAIL: self.evolution is initialized after voice_memory_bridge")
            return False
    else:
        print("⚠️  Could not find both initialization lines")
        return False

if __name__ == "__main__":
    success = check_init_order()
    sys.exit(0 if success else 1)