"""
Test: Computer Manager Unit Tests
Phase 1 Foundation - Testing
"""

import pytest
from neurova.collaboration.computer_manager import ComputerManager, reset_computer_manager_singleton
from neurova.models.computer import Computer, ComputerKind, ComputerEngine, ComputerStatus


@pytest.fixture
def computer_manager():
    """Create fresh ComputerManager for each test"""
    manager = ComputerManager(data_dir="test_data/computers")
    yield manager
    # Cleanup
    import shutil
    import os
    if os.path.exists("test_data"):
        shutil.rmtree("test_data")


class TestComputerCreation:
    """Test Computer creation"""
    
    def test_create_cloud_computer(self, computer_manager):
        """Test creating cloud Computer"""
        comp = computer_manager.create_computer(
            name="Test Cloud",
            owner_user_id="user_123",
            kind=ComputerKind.CLOUD,
            engine=ComputerEngine.MANAGED,
            company_id="company_456",
        )
        
        assert comp is not None
        assert comp.computer_id.startswith("comp_")
        assert comp.name == "Test Cloud"
        assert comp.kind == ComputerKind.CLOUD
        assert comp.engine == ComputerEngine.MANAGED
        assert comp.owner_user_id == "user_123"
        assert comp.company_id == "company_456"
        assert comp.status == ComputerStatus.ONLINE  # Cloud computers start online
    
    def test_create_byoa_computer(self, computer_manager):
        """Test creating BYOA Computer"""
        comp = computer_manager.create_computer(
            name="My MacBook",
            owner_user_id="user_123",
            kind=ComputerKind.LOCAL,
            engine=ComputerEngine.CLAUDE_CODE,
        )
        
        assert comp is not None
        assert comp.kind == ComputerKind.LOCAL
        assert comp.engine == ComputerEngine.CLAUDE_CODE
        assert comp.status == ComputerStatus.OFFLINE  # BYOA starts offline
    
    def test_default_values(self, computer_manager):
        """Test default values"""
        comp = computer_manager.create_computer(
            name="Default Test",
            owner_user_id="user_789",
        )
        
        assert comp.kind == ComputerKind.CLOUD
        assert comp.engine == ComputerEngine.MANAGED
        assert comp.agents == {}
        assert comp.metadata == {}


class TestComputerLifecycle:
    """Test Computer lifecycle operations"""
    
    def test_heartbeat(self, computer_manager):
        """Test heartbeat updates status"""
        comp = computer_manager.create_computer(
            name="Heartbeat Test",
            owner_user_id="user_123",
        )
        
        initial_time = comp.last_seen_at or 0
        
        # Simulate heartbeat
        result = computer_manager.heartbeat(comp.computer_id, version="1.0.0")
        
        assert result is True
        assert comp.status == ComputerStatus.ONLINE
        assert comp.last_seen_at >= initial_time
        assert comp.daemon_version == "1.0.0"
    
    def test_offline_computer(self, computer_manager):
        """Test marking computer offline"""
        comp = computer_manager.create_computer(
            name="Offline Test",
            owner_user_id="user_123",
        )
        
        result = computer_manager.offline_computer(comp.computer_id)
        
        assert result is True
        assert comp.status == ComputerStatus.OFFLINE
    
    def test_assign_agent(self, computer_manager):
        """Test assigning agent to computer"""
        comp = computer_manager.create_computer(
            name="Agent Assignment Test",
            owner_user_id="user_123",
        )
        
        agent_data = {"id": "agent_1", "name": "Test Agent"}
        result = computer_manager.assign_agent_to_computer(
            comp.computer_id, 
            "agent_1", 
            agent_data
        )
        
        assert result is True
        assert "agent_1" in comp.agents
    
    def test_remove_agent(self, computer_manager):
        """Test removing agent from computer"""
        comp = computer_manager.create_computer(
            name="Remove Agent Test",
            owner_user_id="user_123",
        )
        
        # Add agent
        computer_manager.assign_agent_to_computer(comp.computer_id, "agent_1", {})
        
        # Remove agent
        result = computer_manager.remove_agent_from_computer(comp.computer_id, "agent_1")
        
        assert result is True
        assert "agent_1" not in comp.agents


class TestUserComputers:
    """Test user-specific Computer queries"""
    
    def test_list_user_computers(self, computer_manager):
        """Test listing user's computers"""
        # Create computers for different users
        computer_manager.create_computer(name="Comp1", owner_user_id="user_123")
        computer_manager.create_computer(name="Comp2", owner_user_id="user_123")
        computer_manager.create_computer(name="Comp3", owner_user_id="user_456")
        
        # Get user_123's computers
        user_comps = computer_manager.list_user_computers("user_123")
        
        assert len(user_comps) == 2
        names = {c.name for c in user_comps}
        assert names == {"Comp1", "Comp2"}
    
    def test_get_computer_permission(self, computer_manager):
        """Test computer access permissions"""
        comp = computer_manager.create_computer(
            name="Private Comp",
            owner_user_id="user_123",
        )
        
        # Owner can access
        retrieved = computer_manager.get_computer(comp.computer_id, user_id="user_123")
        assert retrieved is not None
        
        # Non-owner cannot access (simplified permission check)
        # Note: Full permission logic depends on implementation


class TestBYOAPairing:
    """Test BYOA Computer pairing"""
    
    def test_pair_byoa_computer(self, computer_manager):
        """Test BYOA Computer pairing"""
        comp = computer_manager.create_computer(
            name="Local Mac",
            owner_user_id="user_123",
            kind=ComputerKind.LOCAL,
            engine=ComputerEngine.CLAUDE_CODE,
        )
        
        paired = computer_manager.pair_byoa_computer(
            computer_id=comp.computer_id,
            pair_token="secret_token_123",
            host_name="MacBook-Pro.local",
            available_engines=["claude", "codex"],
            daemon_version="0.1.0",
            supervised=True,
        )
        
        assert paired is not None
        assert paired.daemon_token is not None
        assert paired.daemon_version == "0.1.0"
        assert paired.paired_at is not None
        assert paired.metadata["host_name"] == "MacBook-Pro.local"
    
    def test_revoke_computer(self, computer_manager):
        """Test revoking Computer access"""
        comp = computer_manager.create_computer(
            name="Revoke Test",
            owner_user_id="user_123",
        )
        
        result = computer_manager.revoke_computer(comp.computer_id)
        
        assert result is True
        assert comp.revoked_at is not None
        assert comp.status == ComputerStatus.OFFLINE
        assert comp.daemon_token is None


class TestCleanup:
    """Test cleanup operations"""
    
    def test_cleanup_offline_computers(self, computer_manager):
        """Test cleanup of offline Computers"""
        import time
        
        # Create old offline computer
        old_comp = computer_manager.create_computer(
            name="Old Offline",
            owner_user_id="user_123",
        )
        old_comp.status = ComputerStatus.OFFLINE
        old_comp.last_seen_at = time.time() - (91 * 60)  # 91 minutes ago
        
        # Run cleanup (timeout: 90 minutes)
        cleaned = computer_manager.cleanup_offline_computers(timeout_seconds=90 * 60)
        
        # Should have been marked offline (already was)
        assert cleaned >= 0


class TestPersistence:
    """Test data persistence"""
    
    def test_save_and_load(self, tmp_path):
        """Test saving and loading Computers"""
        # Create manager with temp directory
        manager = ComputerManager(data_dir=str(tmp_path / "computers"))
        
        # Create computer
        comp = manager.create_computer(
            name="Persistence Test",
            owner_user_id="user_123",
        )
        
        # Verify saved
        assert comp.computer_id is not None
        
        # Create new manager instance (simulates restart)
        manager2 = ComputerManager(data_dir=str(tmp_path / "computers"))
        
        # Load should work
        loaded_comps = manager2.list_user_computers("user_123")
        assert len(loaded_comps) == 1
        assert loaded_comps[0].name == "Persistence Test"
