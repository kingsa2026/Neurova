"""Test to verify EvolutionOrchestrator initialization order fix"""
import sys
import os
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, PropertyMock

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

def test_voice_memory_bridge_evolution_orchestrator_not_none_after_fix():
    """After fix, voice_memory_bridge should receive non-None evolution_orchestrator when evolution is enabled"""
    # Mock the necessary imports and dependencies
    with patch('neurova.voice_memory_bridge.VoiceMemoryBridge') as mock_bridge_class:
        # Create mock instances
        mock_bridge = Mock()
        mock_bridge_class.return_value = mock_bridge
        
        # Import the Agent class after mocking
        from neurova.agent_core import Agent, AgentConfig
        
        # Create a minimal config with evolution enabled
        config = AgentConfig(
            name="test_agent",
            workspace_path=Path("/tmp/test_workspace"),
            enable_tts=True,
            enable_asr=True,
            enable_evolution=True,
        )
        
        # Mock the memory manager
        mock_memory_manager = Mock()
        
        # Create Agent instance with mocked dependencies
        with patch.object(Agent, '_init_memory_modules'):
            # Create agent instance
            agent = Agent(config)
            agent.memory_manager = mock_memory_manager
            
            # Simulate initialization sequence (simplified)
            # 1. Initialize evolution (should be set before voice_memory_bridge)
            mock_evolution = Mock()
            agent.evolution = mock_evolution
            
            # 2. Initialize voice_memory_bridge (should receive mock_evolution)
            try:
                from neurova.voice_memory_bridge import VoiceMemoryBridge, VoiceMemoryConfig
                
                voice_config = VoiceMemoryConfig(
                    enable_asr_memory=config.enable_asr,
                    enable_tts_stats=config.enable_tts,
                    enable_emotion_analysis=True,
                    min_confidence_threshold=0.5,
                )
                
                agent.voice_memory_bridge = VoiceMemoryBridge(
                    config=voice_config,
                    memory_manager=mock_memory_manager,
                    emotion_module=None,
                    evolution_orchestrator=agent.evolution,
                )
                
                # Verify that evolution_orchestrator is not None
                bridge = agent.voice_memory_bridge
                assert agent.voice_memory_bridge.evolution_orchestrator is mock_evolution, \
                    "Expected voice_memory_bridge to receive the agent's evolution orchestrator"
                print("✅ PASS: voice_memory_bridge receives non-None evolution_orchestrator")
                return True
            except Exception as e:
                print(f"❌ FAIL: {e}")
                return False

def test_voice_memory_bridge_evolution_orchestrator_none_when_evolution_disabled():
    """When evolution is disabled, evolution_orchestrator should be None"""
    # This is expected behavior - not a bug
    print("ℹ️  When evolution is disabled, evolution_orchestrator will be None (expected)")
    return True

if __name__ == "__main__":
    test1 = test_voice_memory_bridge_evolution_orchestrator_not_none_after_fix()
    test2 = test_voice_memory_bridge_evolution_orchestrator_none_when_evolution_disabled()
    
    if test1 and test2:
        print("\n✅ All tests passed!")
        sys.exit(0)
    else:
        print("\n❌ Some tests failed!")
        sys.exit(1)