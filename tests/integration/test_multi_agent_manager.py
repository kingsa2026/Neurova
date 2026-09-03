#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for MultiAgentManager (Task 1)

Test coverage:
- NeurovaAgent dataclass
- MultiAgentManager initialization
- Shared components initialization
- Lazy Loading mechanism (get_agent)
- Cognitive-execution loop (execute_with_shared_cerebellum)
- Agent lifecycle management (start/stop/reload)
- Concurrent control
"""

import asyncio
import unittest
from dataclasses import is_dataclass
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from neurova.core.multi_agent_manager import (
    MultiAgentManager,
    NeurovaAgent,
    get_multi_agent_manager,
    reset_multi_agent_manager,
)


class TestNeurovaAgent(unittest.TestCase):
    """Test cases for NeurovaAgent dataclass"""

    def test_neurova_agent_creation(self):
        """Test basic NeurovaAgent creation"""
        agent = NeurovaAgent(
            agent_id="test-agent",
            persona="friendly",
            constitution="always be kind",
        )
        
        self.assertEqual(agent.agent_id, "test-agent")
        self.assertEqual(agent.persona, "friendly")
        self.assertEqual(agent.constitution, "always be kind")
        self.assertIsNone(agent.workspace)
        self.assertEqual(agent.memory_db_path, "")
        self.assertEqual(agent.workspace_dir, "")
        self.assertGreater(agent.created_at, 0)
        self.assertGreater(agent.last_active, 0)

    def test_neurova_agent_is_dataclass(self):
        """Test that NeurovaAgent is a dataclass"""
        self.assertTrue(is_dataclass(NeurovaAgent))

    def test_neurova_agent_is_initialized_no_workspace(self):
        """Test is_initialized property when workspace is None"""
        agent = NeurovaAgent(agent_id="test-agent")
        self.assertFalse(agent.is_initialized)

    def test_neurova_agent_is_initialized_with_workspace_not_started(self):
        """Test is_initialized property when workspace is not started"""
        agent = NeurovaAgent(agent_id="test-agent")
        mock_workspace = MagicMock()
        mock_workspace.started = False
        agent.workspace = mock_workspace
        self.assertFalse(agent.is_initialized)

    def test_neurova_agent_to_dict(self):
        """Test to_dict method"""
        agent = NeurovaAgent(
            agent_id="test-agent",
            persona="friendly",
            constitution="always be kind",
            memory_db_path="/path/to/memory.db",
            workspace_dir="/path/to/workspace",
        )
        
        result = agent.to_dict()
        
        self.assertIsInstance(result, dict)
        self.assertEqual(result["agent_id"], "test-agent")
        self.assertEqual(result["persona"], "friendly")
        self.assertEqual(result["constitution"], "always be kind")
        self.assertEqual(result["memory_db_path"], "/path/to/memory.db")
        self.assertEqual(result["workspace_dir"], "/path/to/workspace")
        self.assertIn("is_initialized", result)
        self.assertIn("created_at", result)
        self.assertIn("last_active", result)


class TestMultiAgentManagerInitialization(unittest.TestCase):
    """Test cases for MultiAgentManager initialization"""

    def setUp(self):
        """Set up test fixtures"""
        self.manager = MultiAgentManager()

    def test_initialization(self):
        """Test basic initialization"""
        self.assertEqual(len(self.manager.agents), 0)
        self.assertIsNone(self.manager.shared_cerebellum)
        self.assertIsNone(self.manager.shared_brainstem)
        self.assertIsNone(self.manager.service_manager)
        self.assertIsNone(self.manager.provider_manager)
        self.assertIsNone(self.manager.event_bus)
        self.assertIsInstance(self.manager._lock, type(asyncio.Lock()))
        self.assertEqual(len(self.manager._pending_starts), 0)
        self.assertEqual(len(self.manager._cleanup_tasks), 0)
        self.assertIsInstance(self.manager._base_workspace_dir, Path)
        self.assertFalse(self.manager._initialized)

    def test_set_base_workspace_dir(self):
        """Test set_base_workspace_dir method"""
        test_dir = "/tmp/test_workspace"
        self.manager.set_base_workspace_dir(test_dir)
        # Use Path for cross-platform compatibility
        self.assertEqual(self.manager._base_workspace_dir, Path(test_dir))

    def test_get_workspace_dir(self):
        """Test get_workspace_dir method"""
        self.manager.set_base_workspace_dir("/tmp/test")
        workspace_dir = self.manager.get_workspace_dir("agent-1")
        self.assertEqual(workspace_dir, Path("/tmp/test/agent-1/workspace"))


class TestInitializeSharedComponents(unittest.IsolatedAsyncioTestCase):
    """Test cases for initialize_shared_components method"""

    def setUp(self):
        """Set up test fixtures"""
        self.manager = MultiAgentManager()

    async def test_initialize_shared_components(self):
        """Test shared components initialization"""
        mock_event_bus = AsyncMock()
        mock_service_manager = AsyncMock()
        mock_provider_manager = AsyncMock()

        await self.manager.initialize_shared_components(
            event_bus=mock_event_bus,
            service_manager=mock_service_manager,
            provider_manager=mock_provider_manager,
        )

        self.assertTrue(self.manager._initialized)
        self.assertEqual(self.manager.event_bus, mock_event_bus)
        self.assertEqual(self.manager.service_manager, mock_service_manager)
        self.assertEqual(self.manager.provider_manager, mock_provider_manager)
        self.assertIsNotNone(self.manager.shared_cerebellum)
        self.assertIsNotNone(self.manager.shared_brainstem)

    async def test_initialize_shared_components_already_initialized(self):
        """Test that initializing already initialized components logs a warning"""
        mock_event_bus = AsyncMock()
        
        await self.manager.initialize_shared_components(event_bus=mock_event_bus)
        
        # Try to initialize again
        with patch('neurova.core.multi_agent_manager.logger') as mock_logger:
            await self.manager.initialize_shared_components(event_bus=mock_event_bus)
            mock_logger.warning.assert_called_once_with("Shared components already initialized")


class TestGetAgent(unittest.IsolatedAsyncioTestCase):
    """Test cases for get_agent method (Lazy Loading)"""

    def setUp(self):
        """Set up test fixtures"""
        self.manager = MultiAgentManager()
        self.manager.set_base_workspace_dir("/tmp/test_agents")

    async def test_get_agent_lazy_loading(self):
        """Test lazy loading of agents"""
        agent_id = "test-agent-1"
        
        # Agent should not exist initially
        self.assertNotIn(agent_id, self.manager.agents)
        
        # Mock Workspace to avoid actual initialization
        with patch('neurova.core.multi_agent_manager.Workspace') as MockWorkspace:
            mock_workspace_instance = AsyncMock()
            MockWorkspace.return_value = mock_workspace_instance
            mock_workspace_instance.start = AsyncMock()
            
            agent = await self.manager.get_agent(agent_id)
            
            self.assertIsInstance(agent, NeurovaAgent)
            self.assertEqual(agent.agent_id, agent_id)
            self.assertIn(agent_id, self.manager.agents)

    async def test_get_agent_caching(self):
        """Test that get_agent caches agents"""
        agent_id = "test-agent-2"
        
        with patch('neurova.core.multi_agent_manager.Workspace') as MockWorkspace:
            mock_workspace_instance = AsyncMock()
            MockWorkspace.return_value = mock_workspace_instance
            mock_workspace_instance.start = AsyncMock()
            
            # First call should create agent
            agent1 = await self.manager.get_agent(agent_id)
            
            # Second call should return cached agent
            agent2 = await self.manager.get_agent(agent_id)
            
            self.assertEqual(agent1, agent2)
            MockWorkspace.assert_called_once()  # Workspace should only be created once

    async def test_get_agent_parallel(self):
        """Test parallel agent creation"""
        agent_id = "test-agent-3"
        
        with patch('neurova.core.multi_agent_manager.Workspace') as MockWorkspace:
            mock_workspace_instance = AsyncMock()
            MockWorkspace.return_value = mock_workspace_instance
            mock_workspace_instance.start = AsyncMock()
            
            # Create multiple tasks to get the same agent
            tasks = [self.manager.get_agent(agent_id) for _ in range(5)]
            results = await asyncio.gather(*tasks)
            
            # All tasks should return the same agent
            self.assertTrue(all(agent == results[0] for agent in results))
            MockWorkspace.assert_called_once()  # Workspace should only be created once


class TestExecuteWithSharedCerebellum(unittest.IsolatedAsyncioTestCase):
    """Test cases for execute_with_shared_cerebellum method"""

    def setUp(self):
        """Set up test fixtures"""
        self.manager = MultiAgentManager()
        self.manager.set_base_workspace_dir("/tmp/test_agents")

    async def test_execute_with_shared_cerebellum_not_initialized(self):
        """Test that execute_with_shared_cerebellum raises RuntimeError when not initialized"""
        with self.assertRaises(RuntimeError) as context:
            await self.manager.execute_with_shared_cerebellum(
                agent_id="test-agent",
                input_context={"user_input": "test"},
            )
        
        self.assertIn("共享组件未初始化", str(context.exception))

    async def test_execute_with_shared_cerebellum_success(self):
        """Test successful execution with shared cerebellum"""
        # Initialize shared components
        mock_event_bus = AsyncMock()
        mock_service_manager = AsyncMock()
        
        await self.manager.initialize_shared_components(
            event_bus=mock_event_bus,
            service_manager=mock_service_manager,
        )
        
        # Mock the shared components
        self.manager.shared_cerebellum = AsyncMock()
        self.manager.shared_cerebellum.decompose_intent = AsyncMock(return_value=MagicMock(
            plan_id="test-plan",
            complexiy=MagicMock(value="simple"),
            tasks=[],
        ))
        
        self.manager.shared_brainstem = AsyncMock()
        self.manager.shared_brainstem.execute_plan = AsyncMock(return_value=MagicMock(
            success=True,
            to_dict=MagicMock(return_value={"status": "success"}),
        ))
        
        # Mock get_agent
        with patch.object(self.manager, 'get_agent') as mock_get_agent:
            mock_agent = NeurovaAgent(agent_id="test-agent")
            mock_agent.workspace = AsyncMock()
            mock_agent.workspace.memory_manager = AsyncMock()
            mock_agent.workspace.memory_manager.retrieve_relevant = AsyncMock(return_value=[])
            mock_agent.workspace.memory_manager.consolidate = AsyncMock()
            mock_get_agent.return_value = mock_agent
            
            result = await self.manager.execute_with_shared_cerebellum(
                agent_id="test-agent",
                input_context={"user_input": "test input"},
            )
            
            self.assertEqual(result["agent_id"], "test-agent")
            self.assertIn("cognition", result)
            self.assertIn("plan", result)
            self.assertIn("execution", result)
            self.assertTrue(result["success"])


class TestAgentLifecycle(unittest.IsolatedAsyncioTestCase):
    """Test cases for agent lifecycle management (start/stop/reload)"""

    def setUp(self):
        """Set up test fixtures"""
        self.manager = MultiAgentManager()
        self.manager.set_base_workspace_dir("/tmp/test_agents")

    async def test_start_agent(self):
        """Test starting an agent"""
        agent_id = "test-agent-start"
        
        with patch('neurova.core.multi_agent_manager.Workspace') as MockWorkspace:
            mock_workspace_instance = AsyncMock()
            MockWorkspace.return_value = mock_workspace_instance
            mock_workspace_instance.start = AsyncMock()
            
            agent = await self.manager.start_agent(
                agent_id=agent_id,
                persona="friendly",
                constitution="be kind",
            )
            
            self.assertIsInstance(agent, NeurovaAgent)
            self.assertEqual(agent.agent_id, agent_id)
            self.assertEqual(agent.persona, "friendly")
            self.assertEqual(agent.constitution, "be kind")

    async def test_stop_agent(self):
        """Test stopping an agent"""
        agent_id = "test-agent-stop"
        
        # First start an agent
        with patch('neurova.core.multi_agent_manager.Workspace') as MockWorkspace:
            mock_workspace_instance = AsyncMock()
            MockWorkspace.return_value = mock_workspace_instance
            mock_workspace_instance.start = AsyncMock()
            mock_workspace_instance.stop = AsyncMock()
            
            await self.manager.start_agent(agent_id=agent_id)
            
            # Now stop it
            await self.manager.stop_agent(agent_id, final=True)
            
            self.assertNotIn(agent_id, self.manager.agents)

    async def test_stop_agent_non_final(self):
        """Test stopping an agent with final=False"""
        agent_id = "test-agent-stop-non-final"
        
        # First start an agent
        with patch('neurova.core.multi_agent_manager.Workspace') as MockWorkspace:
            mock_workspace_instance = AsyncMock()
            MockWorkspace.return_value = mock_workspace_instance
            mock_workspace_instance.start = AsyncMock()
            mock_workspace_instance.stop = AsyncMock()
            
            await self.manager.start_agent(agent_id=agent_id)
            
            # Now stop it with final=False
            await self.manager.stop_agent(agent_id, final=False)
            
            # Agent should still be in the dictionary
            self.assertIn(agent_id, self.manager.agents)

    async def test_reload_agent(self):
        """Test reloading an agent"""
        agent_id = "test-agent-reload"
        
        with patch('neurova.core.multi_agent_manager.Workspace') as MockWorkspace:
            mock_workspace_instance = AsyncMock()
            MockWorkspace.return_value = mock_workspace_instance
            mock_workspace_instance.start = AsyncMock()
            mock_workspace_instance.stop = AsyncMock()
            mock_workspace_instance.get_reusable_services = MagicMock(return_value=[])
            mock_workspace_instance.set_reusable_services = AsyncMock()
            
            # Start agent first
            await self.manager.start_agent(agent_id=agent_id)
            
            # Reload agent
            new_agent = await self.manager.reload_agent(agent_id)
            
            self.assertIsInstance(new_agent, NeurovaAgent)
            self.assertEqual(new_agent.agent_id, agent_id)

    async def test_reload_agent_not_found(self):
        """Test reloading a non-existent agent"""
        with self.assertRaises(ValueError) as context:
            await self.manager.reload_agent("non-existent-agent")
        
        self.assertIn("未找到", str(context.exception))

    async def test_stop_all(self):
        """Test stopping all agents"""
        # Start multiple agents
        with patch('neurova.core.multi_agent_manager.Workspace') as MockWorkspace:
            mock_workspace_instance = AsyncMock()
            MockWorkspace.return_value = mock_workspace_instance
            mock_workspace_instance.start = AsyncMock()
            mock_workspace_instance.stop = AsyncMock()
            
            await self.manager.start_agent(agent_id="agent-1")
            await self.manager.start_agent(agent_id="agent-2")
            await self.manager.start_agent(agent_id="agent-3")
            
            self.assertEqual(len(self.manager.agents), 3)
            
            # Stop all
            await self.manager.stop_all(final=True)
            
            self.assertEqual(len(self.manager.agents), 0)


class TestAgentInfo(unittest.TestCase):
    """Test cases for agent information methods"""

    def setUp(self):
        """Set up test fixtures"""
        self.manager = MultiAgentManager()

    def test_list_agents_empty(self):
        """Test list_agents when no agents exist"""
        result = self.manager.list_agents()
        self.assertEqual(len(result), 0)

    def test_is_agent_loaded_false(self):
        """Test is_agent_loaded when agent is not loaded"""
        result = self.manager.is_agent_loaded("non-existent")
        self.assertFalse(result)

    def test_get_agent_info_not_found(self):
        """Test get_agent_info when agent is not found"""
        result = self.manager.get_agent_info("non-existent")
        self.assertIsNone(result)

    def test_list_agents_info_empty(self):
        """Test list_agents_info when no agents exist"""
        result = self.manager.list_agents_info()
        self.assertEqual(len(result), 0)


class TestConcurrentControl(unittest.IsolatedAsyncioTestCase):
    """Test cases for concurrent control"""

    def setUp(self):
        """Set up test fixtures"""
        self.manager = MultiAgentManager()
        self.manager.set_base_workspace_dir("/tmp/test_agents")

    async def test_concurrent_get_agent(self):
        """Test concurrent access to get_agent"""
        agent_id = "concurrent-agent"
        
        with patch('neurova.core.multi_agent_manager.Workspace') as MockWorkspace:
            mock_workspace_instance = AsyncMock()
            MockWorkspace.return_value = mock_workspace_instance
            mock_workspace_instance.start = AsyncMock()
            
            # Create multiple tasks
            tasks = [self.manager.get_agent(agent_id) for _ in range(10)]
            
            # All should complete without errors
            results = await asyncio.gather(*tasks)
            
            # All should return the same agent
            self.assertTrue(all(agent.agent_id == agent_id for agent in results))


class TestSingletonFunctions(unittest.TestCase):
    """Test cases for singleton functions"""

    def setUp(self):
        """Set up test fixtures"""
        reset_multi_agent_manager()

    def tearDown(self):
        """Clean up after tests"""
        reset_multi_agent_manager()

    def test_get_multi_agent_manager_singleton(self):
        """Test that get_multi_agent_manager returns singleton instance"""
        manager1 = get_multi_agent_manager()
        manager2 = get_multi_agent_manager()
        
        self.assertEqual(manager1, manager2)

    def test_reset_multi_agent_manager(self):
        """Test reset_multi_agent_manager function"""
        manager1 = get_multi_agent_manager()
        reset_multi_agent_manager()
        manager2 = get_multi_agent_manager()
        
        self.assertNotEqual(manager1, manager2)


if __name__ == '__main__':
    unittest.main()
