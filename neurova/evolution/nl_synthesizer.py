"""
NLToolSynthesizer v1.0.0 — 自然语言工具合成器 (Phase 3 P3-3)

职责:
- 解析自然语言描述为结构化需求
- 推断工具分类和所需 Schema
- 建议工具执行序列（基于 PatternMiner + CapabilityGraph）
- 估算合成置信度
- 导出为 SkillTemplate / MarketplaceTool 兼容格式

架构:
  自然语言描述 → NLToolSynthesizer.synthesize()
       │
       ├─▶ parse_description() → 结构化需求
       ├─▶ detect_category() → 工具分类
       ├─▶ generate_schema() → 参数 Schema
       ├─▶ suggest_tool_sequence() → 执行序列
       ├─▶ estimate_confidence() → 置信度
       └─▶ SynthesizedTool → 导出格式
"""

import logging
import re
import typing
import uuid
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


# ────── 数据模型 ──────


class SynthesisStage(Enum):
    """合成阶段"""

    PARSING = "parsing"  # 解析描述
    CLASSIFICATION = "classification"  # 分类推断
    SCHEMA_GENERATION = "schema_generation"  # Schema 生成
    SEQUENCE_SUGGESTION = "sequence_suggestion"  # 序列建议
    CONFIDENCE_ESTIMATION = "confidence_estimation"  # 置信度估算
    COMPLETED = "completed"  # 完成
    FAILED = "failed"  # 失败


@dataclass
class SynthesizedTool:
    """合成工具"""

    tool_id: str = ""
    name: str = ""
    description: str = ""
    category: str = ""
    parameters_schema: typing.Dict[str, typing.Any] = field(default_factory=dict)
    tool_sequence: typing.List[str] = field(default_factory=list)
    confidence: float = 0.0
    stage: SynthesisStage = SynthesisStage.PARSING
    metadata: typing.Dict[str, typing.Any] = field(default_factory=dict)
    created_at: str = ""

    def __post_init__(self):
        if not self.tool_id:
            self.tool_id = str(uuid.uuid4())[:8]
        if not self.created_at:
            import datetime

            self.created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为字典"""
        return {
            "tool_id": self.tool_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "parameters_schema": self.parameters_schema,
            "tool_sequence": self.tool_sequence,
            "confidence": self.confidence,
            "stage": self.stage.value,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


@dataclass
class ToolSynthesisResult:
    """工具合成结果"""

    success: bool = False
    synthesized_tool: typing.Optional[SynthesizedTool] = None
    error_message: str = ""
    processing_time: float = 0.0
    stages_completed: typing.List[SynthesisStage] = field(default_factory=list)
    warnings: typing.List[str] = field(default_factory=list)

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为字典"""
        return {
            "success": self.success,
            "synthesized_tool": self.synthesized_tool.to_dict() if self.synthesized_tool else None,
            "error_message": self.error_message,
            "processing_time": self.processing_time,
            "stages_completed": [s.value for s in self.stages_completed],
            "warnings": self.warnings,
        }


# ────── 工具分类映射 ──────

# 工具分类关键词映射
CATEGORY_KEYWORDS = {
    "search": ["搜索", "查找", "查询", "search", "find", "query", "检索"],
    "file": ["文件", "读取", "写入", "保存", "file", "read", "write", "save", "删除"],
    "web": ["网页", "网络", "爬取", "web", "scrape", "http", "url", "请求"],
    "data": ["数据", "分析", "处理", "data", "analyze", "process", "转换"],
    "ai": ["模型", "预测", "生成", "model", "predict", "generate", "训练"],
    "database": ["数据库", "表", "查询", "database", "table", "sql", "记录"],
    "api": ["接口", "调用", "请求", "api", "call", "request", "端点"],
    "image": ["图片", "图像", "处理", "image", "photo", "picture", "视觉"],
    "text": ["文本", "文字", "处理", "text", "string", "处理", "解析"],
    "automation": ["自动化", "流程", "任务", "automation", "workflow", "task", "执行"],
}


# ────── 主类 ──────


class NLToolSynthesizer:
    """
    自然语言工具合成器

    解析自然语言描述，推断工具需求，生成结构化工具定义。
    """

    def __init__(self, min_confidence: float = 0.3, max_sequence_length: int = 5, enable_pattern_mining: bool = True):
        """
        初始化合成器

        参数:
            min_confidence: 最小置信度阈值
            max_sequence_length: 最大序列长度
            enable_pattern_mining: 是否启用模式挖掘
        """
        self._min_confidence = min_confidence
        self._max_sequence_length = max_sequence_length
        self._enable_pattern_mining = enable_pattern_mining

        # 内置工具模式库
        self._tool_patterns = self._load_tool_patterns()

        logger.info("NLToolSynthesizer initialized")

    def _load_tool_patterns(self) -> typing.Dict[str, typing.Any]:
        """加载工具模式库"""
        return {
            "search_pattern": {
                "keywords": ["搜索", "查找", "查询"],
                "tools": ["memory_search", "web_search"],
                "category": "search",
            },
            "file_pattern": {
                "keywords": ["文件", "读取", "写入"],
                "tools": ["file_read", "file_write"],
                "category": "file",
            },
            "data_pattern": {
                "keywords": ["数据", "分析", "处理"],
                "tools": ["data_process", "data_analyze"],
                "category": "data",
            },
            "web_pattern": {
                "keywords": ["网页", "爬取", "网络"],
                "tools": ["web_fetch", "web_scrape"],
                "category": "web",
            },
        }

    def synthesize(
        self, description: str, context: typing.Optional[typing.Dict[str, typing.Any]] = None
    ) -> ToolSynthesisResult:
        """
        合成工具

        参数:
            description: 自然语言描述
            context: 上下文信息

        返回:
            ToolSynthesisResult: 合成结果
        """
        import time

        start_time = time.time()

        result = ToolSynthesisResult()
        tool = SynthesizedTool()

        try:
            # 阶段1: 解析描述
            tool.stage = SynthesisStage.PARSING
            self.parse_description(description)
            result.stages_completed.append(SynthesisStage.PARSING)

            # 阶段2: 检测分类
            tool.stage = SynthesisStage.CLASSIFICATION
            category = self.detect_category(description)
            tool.category = category
            result.stages_completed.append(SynthesisStage.CLASSIFICATION)

            # 阶段3: 生成 Schema
            tool.stage = SynthesisStage.SCHEMA_GENERATION
            schema = self.generate_schema(description, category)
            tool.parameters_schema = schema
            result.stages_completed.append(SynthesisStage.SCHEMA_GENERATION)

            # 阶段4: 建议工具序列
            tool.stage = SynthesisStage.SEQUENCE_SUGGESTION
            sequence = self.suggest_tool_sequence(description, category)
            tool.tool_sequence = sequence
            result.stages_completed.append(SynthesisStage.SEQUENCE_SUGGESTION)

            # 阶段5: 估算置信度
            tool.stage = SynthesisStage.CONFIDENCE_ESTIMATION
            confidence = self.estimate_confidence(description, category, sequence)
            tool.confidence = confidence
            result.stages_completed.append(SynthesisStage.CONFIDENCE_ESTIMATION)

            # 设置工具信息
            tool.name = self._generate_tool_name(description, category)
            tool.description = description
            tool.tool_id = f"synth_{uuid.uuid4().hex[:8]}"

            # 检查置信度
            if confidence < self._min_confidence:
                result.warnings.append(f"低置信度: {confidence:.2f} < {self._min_confidence}")

            tool.stage = SynthesisStage.COMPLETED
            result.stages_completed.append(SynthesisStage.COMPLETED)

            result.success = True
            result.synthesized_tool = tool

        except Exception as e:
            logger.error("Synthesis failed: %s", e)
            tool.stage = SynthesisStage.FAILED
            result.success = False
            result.error_message = str(e)

        result.processing_time = time.time() - start_time
        return result

    def batch_synthesize(
        self, descriptions: typing.List[str], context: typing.Optional[typing.Dict[str, typing.Any]] = None
    ) -> typing.List[ToolSynthesisResult]:
        """
        批量合成工具

        参数:
            descriptions: 描述列表
            context: 上下文信息

        返回:
            List[ToolSynthesisResult]: 结果列表
        """
        results = []
        for desc in descriptions:
            result = self.synthesize(desc, context)
            results.append(result)
        return results

    def parse_description(self, description: str) -> typing.Dict[str, typing.Any]:
        """
        解析自然语言描述

        参数:
            description: 自然语言描述

        返回:
            Dict: 解析结果
        """
        # 提取关键信息
        words = re.findall(r"[\w\u4e00-\u9fff]+", description.lower())

        # 识别动词和名词
        verbs = []
        nouns = []
        verb_patterns = ["搜索", "查找", "查询", "读取", "写入", "处理", "分析", "生成", "获取", "创建"]
        noun_patterns = ["文件", "数据", "图片", "文本", "网页", "数据库", "接口", "任务", "用户"]

        for word in words:
            if word in verb_patterns:
                verbs.append(word)
            elif word in noun_patterns:
                nouns.append(word)

        return {
            "original": description,
            "words": words,
            "verbs": verbs,
            "nouns": nouns,
            "word_count": len(words),
            "has_verbs": len(verbs) > 0,
            "has_nouns": len(nouns) > 0,
        }

    def detect_category(self, description: str) -> str:
        """
        检测工具分类

        参数:
            description: 自然语言描述

        返回:
            str: 工具分类
        """
        description_lower = description.lower()
        category_scores = {}

        for category, keywords in CATEGORY_KEYWORDS.items():
            score = 0
            for keyword in keywords:
                if keyword in description_lower:
                    score += 1
            if score > 0:
                category_scores[category] = score

        if not category_scores:
            return "general"

        # 返回得分最高的分类
        return max(category_scores.items(), key=lambda x: x[1])[0]

    def generate_schema(self, description: str, category: str) -> typing.Dict[str, typing.Any]:
        """
        生成参数 Schema

        参数:
            description: 自然语言描述
            category: 工具分类

        返回:
            Dict: 参数 Schema
        """
        base_schema = {
            "type": "object",
            "properties": {},
            "required": [],
        }

        # 根据分类生成基础 Schema
        if category == "search":
            base_schema["properties"]["query"] = {"type": "string", "description": "搜索查询"}
            base_schema["required"].append("query")

        elif category == "file":
            base_schema["properties"]["path"] = {"type": "string", "description": "文件路径"}
            base_schema["required"].append("path")

        elif category == "data":
            base_schema["properties"]["data"] = {"type": "object", "description": "输入数据"}
            base_schema["required"].append("data")

        elif category == "web":
            base_schema["properties"]["url"] = {"type": "string", "description": "URL 地址"}
            base_schema["required"].append("url")

        elif category == "api":
            base_schema["properties"]["endpoint"] = {"type": "string", "description": "API 端点"}
            base_schema["required"].append("endpoint")

        # 从描述中提取额外参数
        if "用户" in description or "user" in description.lower():
            base_schema["properties"]["user_id"] = {"type": "string", "description": "用户 ID"}

        if "时间" in description or "time" in description.lower():
            base_schema["properties"]["timestamp"] = {"type": "string", "description": "时间戳"}

        return base_schema

    def suggest_tool_sequence(self, description: str, category: str) -> typing.List[str]:
        """
        建议工具执行序列

        参数:
            description: 自然语言描述
            category: 工具分类

        返回:
            List[str]: 工具序列
        """
        sequence = []

        # 基于分类建议基础工具
        category_tools = {
            "search": ["memory_search"],
            "file": ["file_read"],
            "data": ["data_process"],
            "web": ["web_fetch"],
            "api": ["api_call"],
            "image": ["image_process"],
            "text": ["text_process"],
            "database": ["db_query"],
            "ai": ["model_predict"],
            "automation": ["task_execute"],
        }

        base_tools = category_tools.get(category, ["general_tool"])
        sequence.extend(base_tools)

        # 基于模式库扩展
        for pattern_name, pattern in self._tool_patterns.items():
            for keyword in pattern["keywords"]:
                if keyword in description:
                    for tool in pattern["tools"]:
                        if tool not in sequence:
                            sequence.append(tool)
                    break

        # 限制序列长度
        return sequence[: self._max_sequence_length]

    def estimate_confidence(self, description: str, category: str, tool_sequence: typing.List[str]) -> float:
        """
        估算合成置信度

        参数:
            description: 自然语言描述
            category: 工具分类
            tool_sequence: 工具序列

        返回:
            float: 置信度 (0-1)
        """
        score = 0.0
        max_score = 100.0

        # 1. 描述长度得分 (0-20分)
        word_count = len(re.findall(r"[\w\u4e00-\u9fff]+", description))
        if word_count >= 5:
            score += 20
        elif word_count >= 3:
            score += 15
        elif word_count >= 1:
            score += 10

        # 2. 分类明确性 (0-25分)
        if category != "general":
            score += 25
        else:
            score += 5

        # 3. 工具序列合理性 (0-25分)
        if len(tool_sequence) > 0:
            score += 15
            if len(tool_sequence) <= 3:
                score += 10  # 短序列更可靠

        # 4. 关键词匹配 (0-20分)
        description_lower = description.lower()
        matched_keywords = 0
        for keywords in CATEGORY_KEYWORDS.values():
            for keyword in keywords:
                if keyword in description_lower:
                    matched_keywords += 1
        keyword_score = min(20, matched_keywords * 5)
        score += keyword_score

        # 5. 描述清晰度 (0-10分)
        if any(word in description_lower for word in ["请", "帮我", "需要", "please", "help"]):
            score += 5
        if "?" in description or "？" in description:
            score += 5

        return min(1.0, score / max_score)

    def _generate_tool_name(self, description: str, category: str) -> str:
        """
        生成工具名称

        参数:
            description: 自然语言描述
            category: 工具分类

        返回:
            str: 工具名称
        """
        # 提取关键名词
        words = re.findall(r"[\w\u4e00-\u9fff]+", description.lower())
        nouns = [w for w in words if len(w) > 1][:3]

        if nouns:
            name_part = "_".join(nouns)
        else:
            name_part = category

        return f"{name_part}_tool"


# ────── 单例管理 ──────

_synthesizer_instance: typing.Optional[NLToolSynthesizer] = None
_instance_lock = __import__("threading").Lock()


def get_nl_synthesizer(**kwargs) -> NLToolSynthesizer:
    """获取 NL 工具合成器单例"""
    global _synthesizer_instance
    if _synthesizer_instance is None:
        with _instance_lock:
            if _synthesizer_instance is None:
                _synthesizer_instance = NLToolSynthesizer(**kwargs)
    return _synthesizer_instance


def reset_nl_synthesizer():
    """重置 NL 工具合成器单例"""
    global _synthesizer_instance
    with _instance_lock:
        _synthesizer_instance = None
