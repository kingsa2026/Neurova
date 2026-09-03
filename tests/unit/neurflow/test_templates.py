"""
Neurflow 模板测试 — TDD 垂直切片 10

测试工作流模板功能：
1. 模板注册表
2. 模板加载
3. 模板查询
4. 模板分类
"""
import pytest
from typing import Dict, List, Any

# 导入待测模块
from neurova.collaboration.neurflow.templates import (
    TemplateRegistry,
    get_template_registry,
    reset_template_registry,
)


class TestTemplateRegistry:
    """测试模板注册表"""

    def test_template_registry_initialization(self):
        """测试模板注册表初始化"""
        registry = TemplateRegistry()
        
        # 验证内置模板已加载
        templates = registry.list_templates()
        assert len(templates) == 7  # 7 个领域模板
        
        # 验证模板分类
        categories = registry.get_categories()
        assert "programming" in categories
        assert "writing" in categories
        assert "media" in categories
        assert "document" in categories
        assert "data_analysis" in categories
        assert "ecommerce" in categories
        assert "web_maintenance" in categories

    def test_get_template_existing(self):
        """测试获取已存在的模板"""
        registry = TemplateRegistry()
        
        # 获取编程助手模板
        templates = registry.list_templates(category="programming")
        assert len(templates) == 1
        
        template = templates[0]
        assert template.name == "编程助手"
        assert template.category == "programming"
        assert template.template is True

    def test_get_template_nonexistent(self):
        """测试获取不存在的模板"""
        registry = TemplateRegistry()
        template = registry.get_template("nonexistent_template")
        
        assert template is None

    def test_list_templates_by_category(self):
        """测试按分类列出模板"""
        registry = TemplateRegistry()
        
        # 列出编程模板
        programming_templates = registry.list_templates(category="programming")
        assert len(programming_templates) == 1
        assert all(t.category == "programming" for t in programming_templates)
        
        # 列出写作模板
        writing_templates = registry.list_templates(category="writing")
        assert len(writing_templates) == 1
        assert all(t.category == "writing" for t in writing_templates)

    def test_list_templates_by_tags(self):
        """测试按标签列出模板"""
        registry = TemplateRegistry()
        
        # 列出包含 "tdd" 标签的模板
        tdd_templates = registry.list_templates(tags=["tdd"])
        assert len(tdd_templates) >= 1
        assert all("tdd" in t.tags for t in tdd_templates)
        
        # 列出包含 "video" 标签的模板
        video_templates = registry.list_templates(tags=["video"])
        assert len(video_templates) >= 1
        assert all("video" in t.tags for t in video_templates)

    def test_get_categories(self):
        """测试获取所有分类"""
        registry = TemplateRegistry()
        categories = registry.get_categories()
        
        assert isinstance(categories, list)
        assert len(categories) == 7
        assert "programming" in categories
        assert "writing" in categories
        assert "media" in categories
        assert "document" in categories
        assert "data_analysis" in categories
        assert "ecommerce" in categories
        assert "web_maintenance" in categories

    def test_get_tags(self):
        """测试获取所有标签"""
        registry = TemplateRegistry()
        tags = registry.get_tags()
        
        assert isinstance(tags, list)
        assert len(tags) > 0
        assert "programming" in tags
        assert "writing" in tags
        assert "video" in tags

    def test_template_structure(self):
        """测试模板结构完整性"""
        registry = TemplateRegistry()
        templates = registry.list_templates()
        
        for template in templates:
            # 验证必需字段
            assert template.id is not None
            assert template.name is not None
            assert template.description is not None
            assert template.version is not None
            assert template.category is not None
            assert template.template is True
            
            # 验证节点和边
            assert len(template.nodes) > 0
            assert len(template.edges) > 0
            
            # 验证节点类型
            node_types = [n.type for n in template.nodes]
            assert "builtin:start" in node_types
            assert "builtin:end" in node_types


class TestTemplateRegistrySingleton:
    """测试模板注册表单例模式"""

    def test_get_template_registry_singleton(self):
        """测试 get_template_registry 返回单例"""
        registry1 = get_template_registry()
        registry2 = get_template_registry()
        
        assert registry1 is registry2

    def test_reset_template_registry(self):
        """测试重置单例"""
        registry1 = get_template_registry()
        reset_template_registry()
        registry2 = get_template_registry()
        
        assert registry1 is not registry2


class TestProgrammingTemplate:
    """测试编程助手模板"""

    def test_programming_template_structure(self):
        """测试编程助手模板结构"""
        registry = TemplateRegistry()
        templates = registry.list_templates(category="programming")
        assert len(templates) == 1
        
        template = templates[0]
        assert template.name == "编程助手"
        assert template.category == "programming"
        assert "tdd" in template.tags
        
        # 验证节点
        node_ids = [n.id for n in template.nodes]
        assert "start" in node_ids
        assert "end" in node_ids
        assert "analyze_requirements" in node_ids
        assert "tdd_implementation" in node_ids
        assert "code_review" in node_ids
        assert "quality_check" in node_ids
        assert "evolution_learning" in node_ids
        assert "code_optimization" in node_ids
        assert "merge_results" in node_ids

    def test_programming_template_edges(self):
        """测试编程助手模板边连接"""
        registry = TemplateRegistry()
        templates = registry.list_templates(category="programming")
        template = templates[0]
        
        # 验证边连接
        edges = template.edges
        assert len(edges) == 9  # 9 条边连接
        
        # 验证关键连接
        source_targets = [(e.source, e.target) for e in edges]
        assert ("start", "analyze_requirements") in source_targets
        assert ("analyze_requirements", "tdd_implementation") in source_targets
        assert ("tdd_implementation", "code_review") in source_targets
        assert ("code_review", "quality_check") in source_targets

    def test_programming_template_variables(self):
        """测试编程助手模板变量"""
        registry = TemplateRegistry()
        templates = registry.list_templates(category="programming")
        template = templates[0]
        
        # 验证变量
        variables = template.variables
        assert len(variables) == 3
        
        var_names = [v.name for v in variables]
        assert "max_iterations" in var_names
        assert "quality_threshold" in var_names
        assert "include_comments" in var_names


class TestWritingTemplate:
    """测试文学创作模板"""

    def test_writing_template_structure(self):
        """测试文学创作模板结构"""
        registry = TemplateRegistry()
        templates = registry.list_templates(category="writing")
        assert len(templates) == 1
        
        template = templates[0]
        assert template.name == "文学创作"
        assert template.category == "writing"
        assert "writing" in template.tags
        
        # 验证节点
        node_ids = [n.id for n in template.nodes]
        assert "start" in node_ids
        assert "end" in node_ids
        assert "outline" in node_ids
        assert "research" in node_ids
        assert "draft" in node_ids
        assert "human_review" in node_ids
        assert "polish" in node_ids


class TestMediaTemplate:
    """测试媒体创作模板"""

    def test_media_template_structure(self):
        """测试媒体创作模板结构"""
        registry = TemplateRegistry()
        templates = registry.list_templates(category="media")
        assert len(templates) == 1
        
        template = templates[0]
        assert template.name == "媒体创作"
        assert template.category == "media"
        assert "video" in template.tags
        
        # 验证节点
        node_ids = [n.id for n in template.nodes]
        assert "start" in node_ids
        assert "end" in node_ids
        assert "script" in node_ids
        assert "voiceover" in node_ids
        assert "thumbnail" in node_ids
        assert "video_gen" in node_ids
        assert "merge" in node_ids


class TestDocumentTemplate:
    """测试文档处理模板"""

    def test_document_template_structure(self):
        """测试文档处理模板结构"""
        registry = TemplateRegistry()
        templates = registry.list_templates(category="document")
        assert len(templates) == 1
        
        template = templates[0]
        assert template.name == "文档处理"
        assert template.category == "document"
        assert "document" in template.tags


class TestDataAnalysisTemplate:
    """测试数据分析模板"""

    def test_data_analysis_template_structure(self):
        """测试数据分析模板结构"""
        registry = TemplateRegistry()
        templates = registry.list_templates(category="data_analysis")
        assert len(templates) == 1
        
        template = templates[0]
        assert template.name == "数据分析"
        assert template.category == "data_analysis"
        assert "data" in template.tags


class TestEcommerceTemplate:
    """测试电商运营模板"""

    def test_ecommerce_template_structure(self):
        """测试电商运营模板结构"""
        registry = TemplateRegistry()
        templates = registry.list_templates(category="ecommerce")
        assert len(templates) == 1
        
        template = templates[0]
        assert template.name == "电商运营"
        assert template.category == "ecommerce"
        assert "ecommerce" in template.tags


class TestWebMaintenanceTemplate:
    """测试网站维护模板"""

    def test_web_maintenance_template_structure(self):
        """测试网站维护模板结构"""
        registry = TemplateRegistry()
        templates = registry.list_templates(category="web_maintenance")
        assert len(templates) == 1
        
        template = templates[0]
        assert template.name == "网站维护"
        assert template.category == "web_maintenance"
        assert "web" in template.tags