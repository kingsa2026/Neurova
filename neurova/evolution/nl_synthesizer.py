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

import hashlib
import re

from neurova.core.logger import get_logger
import typing
import uuid
from dataclasses import dataclass, field
from enum import Enum

logger = get_logger(__name__)


# ────── 数据模型 ──────


class SynthesisStage(Enum):
    """合成阶段"""

    PARSING = "parsing"  # 解析描述
    CLASSIFICATION = "classification"  # 分类推断
    SCHEMA_GENERATION = "schema_generation"  # Schema 生成
    SEQUENCE_SUGGESTION = "sequence_suggestion"  # 序列建议
    CONFIDENCE_ESTIMATION = "confidence_estimation"  # 置信度估算
    COMPLETED = "completed"  # 完成
    PENDING_REVIEW = "pending_review"  # 置信闸拦下：待人工复核，不得进注册路径
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

    def __init__(
        self,
        min_confidence: float = 0.5,
        max_sequence_length: int = 5,
        enable_pattern_mining: bool = True,
        pattern_miner: typing.Any = None,
    ):
        """
        初始化合成器

        参数:
            min_confidence: 最小置信度阈值（工单 014 从 0.3 抬到 0.5）。
                抬阈值不是收紧口径，是让门**可达**：`estimate_confidence` 对任何
                非空描述都有 ≈0.45 的下界（分类为 general 也给 5 分、序列只要非空
                就满 25 分），配 0.3 时低置信分支永远不触发——门做实了却仍不存在。
                实测样本：0.45（"帮我 zzzz"）/0.5/0.65（"帮我搜索文件"）/0.7。
                估器本身"有序列即满分"的虚高是同批次的另一处待修（属质量度量面），
                本处不靠改打分公式交差，避免把注册率一次性打没。
            max_sequence_length: 最大序列长度
            enable_pattern_mining: 是否启用模式挖掘
            pattern_miner: 可选的 PatternMiner 实例（P0-B3 修复：
                agent_core.py 传入 pattern_miner=a.pattern_miner 以集成进化子系统。
                之前签名不接受此参数，导致 TypeError → tool_synthesizer 永远为 None）
        """
        self._min_confidence = min_confidence
        self._max_sequence_length = max_sequence_length
        self._enable_pattern_mining = enable_pattern_mining
        # P0-B3: 保留 pattern_miner 引用供合成流程使用（可选）
        self._pattern_miner = pattern_miner
        # 置信闸拦下计数（工单 014）：008 指标面就绪前的可观测落点
        self.low_confidence_rejections = 0
        # 字母表校验拦下计数（T-04）：与上面同一类可观测落点，含义是"产出含未注册名"。
        # 二者分开计数：低置信是估分问题，字母表不合法是**名字根本不存在**，
        # 混在一个计数器里就再也分不清"该调估分器"还是"该补原语"。
        self.unregistered_alphabet_rejections = 0

        # 分类 → 候选原语（**单源**分类表；未知分类不在表内，即"无合法候选"）
        self._category_primitives = self._load_category_primitives()

        # 内置工具模式库
        self._tool_patterns = self._load_tool_patterns()

        logger.info("NLToolSynthesizer initialized (pattern_miner=%s)", pattern_miner is not None)

    def _load_category_primitives(self) -> typing.Dict[str, typing.List[str]]:
        """加载"分类 → 候选原语"表（单源）。

        表里的名字一律取自**真实注册名**。原表 10 个分类里 7 个是幻名
        （`db_query`/`data_process`/`image_process`/`text_process`/
        `model_predict`/`task_execute`/`api_call` 注册处均为 0），
        产出的序列因此是模型读不到的路标；未知分类还落到同样不存在的
        `general_tool`。现在：表内只有已注册名，分类不在表内即**无候选**。
        """
        return {
            "search": ["memory_search"],
            "file": ["file_read"],
            "data": ["file_parse"],
            "web": ["web_fetch"],
            "image": ["file_parse"],
            "text": ["file_read"],
            "ai": ["deep_research"],
            "automation": ["update_plan"],
        }
        # `database` 与 `api` **不在此表里**：它们是"确实缺原语"的分类，不是
        # "有原语但名字写错了"。硬塞一个 `file_parse` 进去等于给模型指一条读不到
        # 数据集的路（`file_parse` 只收工作区内的 file_path）。
        # 缺原语就该在合成面上诚实暴露为"无合法候选、转人工复核"；
        # 等真正补上 `query_database` 后，再把 `database` 一行加到这里——
        # 单一事实源，不两处各写一份。

    def _load_tool_patterns(self) -> typing.Dict[str, typing.Any]:
        """加载工具模式库。

        表里的 `tools` 一律取自**真实注册名**（`builtin_tools.get_registered_tool_names`
        是唯一读侧）。原实现里 `data_process` / `data_analyze` / `web_scrape` 三个名字
        全仓注册处为 0 —— 合成序列经这条表产出后，模型拿到的是一条读不到的工具路标。
        """
        from neurova.builtin_tools import get_registered_tool_names

        registered = set(get_registered_tool_names())

        def _pick(*names: str) -> typing.List[str]:
            return [name for name in names if name in registered]

        return {
            "search_pattern": {
                "keywords": ["搜索", "查找", "查询"],
                "tools": _pick("memory_search", "web_search"),
                "category": "search",
            },
            "file_pattern": {
                "keywords": ["文件", "读取", "写入"],
                "tools": _pick("file_read", "file_write"),
                "category": "file",
            },
            "data_pattern": {
                "keywords": ["数据", "分析", "处理"],
                "tools": _pick("file_parse", "calculator"),
                "category": "data",
            },
            "web_pattern": {
                "keywords": ["网页", "爬取", "网络"],
                "tools": _pick("web_fetch", "web_search"),
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
            # Bug N-10 修复: 原代码丢弃 parse_description 返回值，下游方法
            # (detect_category/generate_schema/suggest_tool_sequence) 全部重新
            # 从字符串解析，既浪费计算又丢失结构化信息。现将解析结果存入
            # tool.metadata，使合成工具携带结构化解析信息供消费者使用。
            parsed_description = self.parse_description(description)
            tool.metadata["parsed_description"] = parsed_description
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

            # 阶段4.5: 字母表闸（T-04）——序列里出现**未注册名**即拒绝合成。
            # 为什么摆在置信度之前：名字不存在与估分高低无关。放后面会让
            # "高置信的幻名序列"以 COMPLETED 出现在产物面上 —— 那正是 T-03
            # 打开入口后幽灵技能放大器的形态。D4：不降级为部分合成。
            # 空序列（未知分类无合法候选）**不在此另开分支**：它由紧随其后的
            # 既有置信闸处置（序列为空自然拿不到"序列合理性"分，估分即低）。
            # 单开一条分支等于第二套拦截口径 —— 教义第 6 条，且会让"调阈值"
            # 这条既有旋钮对未知分类失效。
            from neurova.builtin_tools import get_registered_tool_names

            _unregistered = [
                _name for _name in sequence if _name not in set(get_registered_tool_names())
            ]
            if _unregistered:
                self.unregistered_alphabet_rejections += 1
                tool.stage = SynthesisStage.PENDING_REVIEW
                result.stages_completed.append(SynthesisStage.PENDING_REVIEW)
                result.success = False
                result.error_message = (
                    f"合成序列含未注册工具 {_unregistered}（字母表不合法，转人工复核）"
                )
                tool.name = self._generate_tool_name(description, category)
                tool.description = description
                tool.tool_id = f"synth_{uuid.uuid4().hex[:8]}"
                result.synthesized_tool = tool
                logger.warning("NL 合成被字母表闸拦下: %s", result.error_message)
                result.processing_time = time.time() - start_time
                return result

            # 阶段5: 估算置信度
            tool.stage = SynthesisStage.CONFIDENCE_ESTIMATION
            confidence = self.estimate_confidence(description, category, sequence)
            tool.confidence = confidence
            result.stages_completed.append(SynthesisStage.CONFIDENCE_ESTIMATION)

            # 设置工具信息
            tool.name = self._generate_tool_name(description, category)
            tool.description = description
            tool.tool_id = f"synth_{uuid.uuid4().hex[:8]}"

            # 置信闸（工单 014）：低置信是闸，不是提示。
            # 原实现在这里只 warnings.append 一条，随后无条件 COMPLETED + success=True，
            # 调用方只看这两个字段 ⇒ 门不存在。拦下时产物仍挂在 synthesized_tool 上
            # 供人工复核（拦 ≠ 丢），warnings 保留为信息位但不再是唯一处置。
            if confidence < self._min_confidence:
                result.warnings.append(f"低置信度: {confidence:.2f} < {self._min_confidence}")
                self.low_confidence_rejections += 1
                tool.stage = SynthesisStage.PENDING_REVIEW
                result.stages_completed.append(SynthesisStage.PENDING_REVIEW)
                result.success = False
                result.error_message = (
                    f"置信度 {confidence:.2f} 低于阈值 {self._min_confidence}，转人工复核"
                )
                result.synthesized_tool = tool
                # 指标面（工单 008）就绪前先落日志，计数同步落在
                # `low_confidence_rejections` 上，便于后续接进质量读数。
                logger.warning(
                    "NL 合成被置信闸拦下: %s (confidence=%.2f < %.2f)",
                    tool.name, confidence, self._min_confidence,
                )
            else:
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

        # Bug N-10 修复: CJK 文本无空格分隔，re.findall 把整段中文当作一个 word，
        # 导致 `word in verb_patterns` 永远不匹配（"搜索用户数据" != "搜索"）。
        # 改为在原文中做子串匹配，与 detect_category 的 keyword 匹配方式一致。
        desc_lower = description.lower()
        for pattern in verb_patterns:
            if pattern in desc_lower:
                verbs.append(pattern)
        for pattern in noun_patterns:
            if pattern in desc_lower:
                nouns.append(pattern)

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

    def resolveAlphabetCandidates(self, category: str, description: str) -> typing.List[str]:
        """给定分类与描述，给出**已注册**的候选原语（单源解析点）。

        与 `suggest_tool_sequence` 同处一个类、同一份读侧：
        候选来源只有两处——分类基础表与模式库表，两处都由
        `builtin_tools.get_registered_tool_names()` 过滤后返回。
        未知分类**不编造**候选，也没有兜底幻名：返回空列表，
        由调用方转人工复核（D4：不降级为部分合成）。
        """
        from neurova.builtin_tools import get_registered_tool_names

        registered = set(get_registered_tool_names())
        if category not in self._category_primitives:
            return []

        base = [name for name in self._category_primitives[category] if name in registered]
        for pattern in self._tool_patterns.values():
            if any(keyword in description for keyword in pattern["keywords"]):
                base.extend(name for name in pattern["tools"] if name in registered)
        # 去重保序（同名原语只建议一次）
        seen: typing.Set[str] = set()
        return [name for name in base if not (name in seen or seen.add(name))]

    def suggest_tool_sequence(self, description: str, category: str) -> typing.List[str]:
        """
        建议工具执行序列

        参数:
            description: 自然语言描述
            category: 工具分类

        返回:
            List[str]: 工具序列
        """
        sequence = self.resolveAlphabetCandidates(category, description)

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

        Bug T-3 修复: OpenAI function calling 工具名规范为 ^[a-zA-Z0-9_-]{1,64}$，
        不允许中文。原正则 [\\u4e00-\\u9fff] 匹配中文字符导致工具名含中文被 LLM 拒绝。
        修复: 只提取 ASCII 单词，中文描述回退到 category（category 来自 CATEGORY_KEYWORDS 映射，恒为 ASCII）。
        """
        # 只提取 ASCII 单词（字母开头，含字母数字下划线），避免中文进入工具名
        words = re.findall(r"[a-zA-Z][a-zA-Z0-9_]+", description.lower())
        nouns = [w for w in words if len(w) > 1][:3]

        if nouns:
            name_part = "_".join(nouns)
        else:
            # 中文描述无 ASCII 词时回退到 category（恒为 ASCII，如 search/file/web）
            name_part = category

        # 唯一化后缀：注册表按 name 建键，纯词干名会让"同一描述连跑两次"的两个
        # 产物互相顶替（启动日志累计 10 条 `技能同名覆盖（name=general_tool/ai_tool）`）。
        # 后缀取描述指纹——同描述的重复合成因此**幂等**（同名的确是同一个东西），
        # 不同描述必不撞名。不取随机数：随机后缀会让"重复合成"变成产生一堆垃圾技能。
        fingerprint = hashlib.sha256(description.encode("utf-8", "replace")).hexdigest()[:8]
        return f"{name_part}_{fingerprint}_tool"


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
