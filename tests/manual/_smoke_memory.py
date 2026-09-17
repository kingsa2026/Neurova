"""Quick smoke test for memory closure"""
import sys
sys.path.insert(0, r'e:\项目\neurova')

from neurova.cognitive_layers.memory_layer.conversation_buffer import ConversationMemoryBuffer

buffer = ConversationMemoryBuffer(turn_limit=10)
r1 = buffer.add_user_message("hello")
r2 = buffer.add_agent_message("hi there")
stats = buffer.get_stats()
print(f"add_user: {r1}, add_agent: {r2}")
print(f"buffer_size: {stats['buffer_size']}")
print(f"complete_turns: {stats['conversation']['complete_turns']}")
print(f"should_flush: {stats['should_flush']}")
print("PASS: basic buffer test")
