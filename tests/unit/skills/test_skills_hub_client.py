"""
Test cases for neurova.skills.hub_client
"""
import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from neurova.skills.hub_client import (
    SkillSource,
    RemoteSkill,
    SkillHubClient,
    _github_cache_ttl,
    _http_timeout,
    _http_retries,
)


class TestSkillSource:
    """Test cases for SkillSource enum."""
    
    def test_skill_source_values(self):
        """Test SkillSource enum values."""
        assert SkillSource.GITHUB.value == "github"
        assert SkillSource.CLAWHUB.value == "clawhub"
        assert SkillSource.LOBEHUB.value == "lobehub"
        assert SkillSource.LOCAL.value == "local"
    
    def test_skill_source_members(self):
        """Test SkillSource enum members."""
        assert len(SkillSource) >= 4
        assert "GITHUB" in SkillSource.__members__
        assert "CLAWHUB" in SkillSource.__members__
        assert "LOBEHUB" in SkillSource.__members__
        assert "LOCAL" in SkillSource.__members__


class TestRemoteSkill:
    """Test cases for RemoteSkill class."""
    
    def test_remote_skill_creation(self):
        """Test creating a RemoteSkill instance."""
        skill = RemoteSkill(
            name="test_skill",
            source=SkillSource.GITHUB,
            description="A test skill",
            version="1.0.0",
            author="test_author",
        )
        assert skill.name == "test_skill"
        assert skill.source == SkillSource.GITHUB
        assert skill.description == "A test skill"
        assert skill.version == "1.0.0"
        assert skill.author == "test_author"
    
    def test_remote_skill_defaults(self):
        """Test RemoteSkill default values."""
        skill = RemoteSkill(name="test_skill", source=SkillSource.GITHUB)
        assert skill.name == "test_skill"
        assert skill.source == SkillSource.GITHUB
        assert skill.description == ""
        assert skill.version == "0.0.0"
        assert skill.author == ""
        assert skill.url == ""
        assert skill.download_url == ""
    
    def test_remote_skill_to_dict(self):
        """Test converting RemoteSkill to dictionary."""
        skill = RemoteSkill(
            name="test_skill",
            source=SkillSource.GITHUB,
            description="A test skill",
            version="1.0.0",
        )
        data = skill.to_dict()
        assert data["name"] == "test_skill"
        assert data["source"] == "github"
        assert data["description"] == "A test skill"
        assert data["version"] == "1.0.0"
    
    def test_remote_skill_from_dict(self):
        """Test creating RemoteSkill from dictionary."""
        data = {
            "name": "test_skill",
            "source": "github",
            "description": "A test skill",
            "version": "1.0.0",
        }
        skill = RemoteSkill.from_dict(data)
        assert skill.name == "test_skill"
        assert skill.source == SkillSource.GITHUB


class TestSkillHubClient:
    """Test cases for SkillHubClient class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.client = SkillHubClient(
            base_dir=self.temp_dir,
            config={"enabled": True},
        )
    
    def teardown_method(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_skill_hub_client_creation(self):
        """Test creating a SkillHubClient instance."""
        assert self.client is not None
        assert hasattr(self.client, 'search_skills')
        assert hasattr(self.client, 'install_skill')
    
    def test_skill_hub_client_has_proper_attributes(self):
        """Test that SkillHubClient has all required attributes."""
        assert hasattr(self.client, '_base_dir')
        assert hasattr(self.client, '_sources')
        assert hasattr(self.client, '_cache')
        assert hasattr(self.client, '_config')
    
    def test_register_source(self):
        """Test registering a skill source."""
        self.client.register_source(
            name="test_source",
            source_type=SkillSource.GITHUB,
            config={"repo": "test/repo"},
        )
        
        assert "test_source" in self.client._sources
    
    def test_register_default_sources(self):
        """Test that default sources are registered."""
        # Should have at least GitHub source
        assert len(self.client._sources) > 0
    
    @patch('neurova.skills.hub_client._http_json_get')
    def test_search_github(self, mock_http_get):
        """Test searching GitHub for skills."""
        mock_http_get.return_value = {
            "items": [
                {
                    "name": "test-skill",
                    "description": "A test skill",
                    "html_url": "https://github.com/test/test-skill",
                    "owner": {"login": "test"},
                },
            ],
        }
        
        results = self.client._search_github("test", limit=10)
        
        assert len(results) > 0
        assert results[0].name == "test-skill"
        assert results[0].source == SkillSource.GITHUB
    
    def test_search_skills(self):
        """Test searching skills across all sources."""
        # Mock the individual search methods
        self.client._search_github = Mock(return_value=[
            RemoteSkill(name="github_skill", source=SkillSource.GITHUB),
        ])
        self.client._search_clawhub = Mock(return_value=[
            RemoteSkill(name="clawhub_skill", source=SkillSource.CLAWHUB),
        ])
        
        results = self.client.search_skills("test", sources=["github", "clawhub"])
        
        assert len(results) == 2
    
    def test_install_skill(self):
        """Test installing a skill."""
        # Mock the install method
        self.client._install_from_github = Mock(return_value=True)
        
        skill = RemoteSkill(
            name="test_skill",
            source=SkillSource.GITHUB,
            download_url="https://github.com/test/test-skill/archive/main.zip",
        )
        
        result = self.client.install_skill(skill)
        
        assert result is True
        self.client._install_from_github.assert_called_once()
    
    def test_get_skill_latest_version(self):
        """Test getting latest skill version."""
        # Mock the version methods
        self.client._get_github_skill_version = Mock(return_value="2.0.0")
        
        skill = RemoteSkill(
            name="test_skill",
            source=SkillSource.GITHUB,
            version="1.0.0",
        )
        
        version = self.client.get_skill_latest_version(skill)
        
        assert version == "2.0.0"
    
    def test_list_remote_skills(self):
        """Test listing remote skills."""
        # Mock the list methods
        self.client._list_github_skills = Mock(return_value=[
            RemoteSkill(name="skill1", source=SkillSource.GITHUB),
            RemoteSkill(name="skill2", source=SkillSource.GITHUB),
        ])
        
        skills = self.client.list_remote_skills(source="github")
        
        assert len(skills) == 2


class TestHelperFunctions:
    """Test cases for helper functions."""
    
    def test_github_cache_ttl(self):
        """Test GitHub cache TTL function."""
        ttl = _github_cache_ttl()
        assert isinstance(ttl, int)
        assert ttl > 0
    
    def test_http_timeout(self):
        """Test HTTP timeout function."""
        timeout = _http_timeout()
        assert isinstance(timeout, (int, float))
        assert timeout > 0
    
    def test_http_retries(self):
        """Test HTTP retries function."""
        retries = _http_retries()
        assert isinstance(retries, int)
        assert retries >= 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])