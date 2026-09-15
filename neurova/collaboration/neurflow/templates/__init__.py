"""
Neurflow 工作流模板

提供预定义的工作流模板，用于快速创建常见工作流。

模板分类：
- programming: 编程助手模板
- writing: 文学创作模板
- media: 媒体创作模板
- document: 文档处理模板
- data_analysis: 数据分析模板
- ecommerce: 电商运营模板
- web_maintenance: 网站维护模板
"""

from typing import Dict, List, Optional

from ..models import WorkflowDefinition


class TemplateRegistry:
    """模板注册表 — 管理所有工作流模板"""

    def __init__(self):
        self._templates: Dict[str, WorkflowDefinition] = {}
        self._load_builtin_templates()

    def _load_builtin_templates(self):
        """加载内置模板"""
        # 延迟加载，避免循环导入
        from .data_analysis import get_data_analysis_template
        from .document import get_document_template
        from .ecommerce import get_ecommerce_template
        from .media import get_media_template
        from .programming import get_programming_template
        from .web_maintenance import get_web_maintenance_template
        from .writing import get_writing_template

        templates = [
            get_programming_template(),
            get_writing_template(),
            get_media_template(),
            get_document_template(),
            get_data_analysis_template(),
            get_ecommerce_template(),
            get_web_maintenance_template(),
        ]

        for template in templates:
            self._templates[template.id] = template

    def get_template(self, template_id: str) -> Optional[WorkflowDefinition]:
        """获取模板"""
        return self._templates.get(template_id)

    def list_templates(
        self, category: Optional[str] = None, tags: Optional[List[str]] = None
    ) -> List[WorkflowDefinition]:
        """列出模板

        Args:
            category: 按分类过滤（可选）
            tags: 按标签过滤（可选）

        Returns:
            模板列表
        """
        templates = list(self._templates.values())

        # 按分类过滤
        if category:
            templates = [t for t in templates if t.category == category]

        # 按标签过滤
        if tags:
            templates = [t for t in templates if any(tag in t.tags for tag in tags)]

        return templates

    def get_categories(self) -> List[str]:
        """获取所有分类"""
        categories = set()
        for template in self._templates.values():
            categories.add(template.category)
        return sorted(list(categories))

    def get_tags(self) -> List[str]:
        """获取所有标签"""
        tags = set()
        for template in self._templates.values():
            tags.update(template.tags)
        return sorted(list(tags))


# 单例管理
_template_registry_instance: Optional[TemplateRegistry] = None


def seed_short_drama_template(storage) -> bool:
    """启动种子：短剧一键成片模板
    写入工作流库（id 固定、幂等——已存在不覆盖用户修改）。

    Returns:
        True=本次新种入，False=已存在跳过。
    """
    from .short_drama import SHORT_DRAMA_TEMPLATE_ID, get_short_drama_template

    try:
        if storage.get_workflow(SHORT_DRAMA_TEMPLATE_ID) is not None:
            return False
        storage.save_workflow(get_short_drama_template(), user_id=None)
        return True
    except Exception:  # noqa: BLE001 - 种子失败不阻塞启动（模板非关键路径）
        return False


def get_template_registry() -> TemplateRegistry:
    """获取模板注册表单例"""
    global _template_registry_instance

    if _template_registry_instance is None:
        _template_registry_instance = TemplateRegistry()

    return _template_registry_instance


def reset_template_registry() -> None:
    """重置模板注册表单例"""
    global _template_registry_instance
    _template_registry_instance = None


# 便捷导出
__all__ = [
    "TemplateRegistry",
    "get_template_registry",
    "reset_template_registry",
    "seed_short_drama_template",
]
