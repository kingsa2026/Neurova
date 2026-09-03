"""
Neurflow AI 短剧视频生成节点测试 — TDD 垂直切片

测试 AI 短剧 / 短剧视频生成节点定义与执行器功能：
1. 短剧相关节点定义（剧本 / 分镜 / 场景 / 配音 / 字幕 / 合成 / 发布）
2. 节点注册到注册表
3. 节点执行器行为
4. 模板引用的节点完整性
"""
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

# 导入待测模块
from neurova.collaboration.neurflow.drama_nodes import (
    DRAMA_NODES,
    register_drama_nodes,
    get_drama_executors,
    # 执行器
    exec_short_drama_script,
    exec_storyboard,
    exec_scene_gen,
    exec_voice_over,
    exec_subtitle_gen,
    exec_video_compose,
    exec_video_publish,
    exec_tts,
)

# 短剧视频生成节点类型集合
EXPECTED_DRAMA_TYPES = {
    "builtin:short-drama-script",  # 短剧剧本生成
    "builtin:storyboard",          # 分镜脚本
    "builtin:scene-gen",           # 场景画面生成
    "builtin:voice-over",          # 配音 / 旁白生成
    "builtin:subtitle-gen",        # 字幕生成
    "builtin:video-compose",       # 视频合成
    "builtin:video-publish",       # 短剧发布
    "builtin:tts",                 # 文本转语音（模板引用）
}


class TestDramaNodesDefinition:
    """测试短剧视频生成节点定义"""

    def test_has_all_drama_nodes(self):
        """应包含所有短剧视频生成节点"""
        types = [n["type"] for n in DRAMA_NODES]
        for t in EXPECTED_DRAMA_TYPES:
            assert t in types, f"缺少短剧节点: {t}"

    def test_all_nodes_media_category(self):
        """所有节点分类应为 media"""
        for node in DRAMA_NODES:
            assert node["category"] == "media", f"节点分类错误: {node['type']}"

    def test_node_has_required_fields(self):
        """每个节点应有必需字段"""
        for node in DRAMA_NODES:
            assert "type" in node, f"节点缺少 type: {node}"
            assert "label" in node, f"节点缺少 label: {node}"
            assert "icon" in node, f"节点缺少 icon: {node}"
            assert "category" in node, f"节点缺少 category: {node}"
            assert "description" in node, f"节点缺少 description: {node}"
            assert "sub_blocks" in node, f"节点缺少 sub_blocks: {node}"
            assert "inputs" in node, f"节点缺少 inputs: {node}"
            assert "outputs" in node, f"节点缺少 outputs: {node}"

    def test_node_type_format(self):
        """节点类型应以 builtin: 开头"""
        for node in DRAMA_NODES:
            assert node["type"].startswith("builtin:"), f"节点类型格式错误: {node['type']}"

    def test_short_drama_script_definition(self):
        """短剧剧本节点应包含类型、集数、剧情等字段"""
        node = next(n for n in DRAMA_NODES if n["type"] == "builtin:short-drama-script")
        assert node["label"] == "短剧剧本生成"
        block_ids = [b.get("id") or b.get("name") for b in node["sub_blocks"]]
        assert "genre" in block_ids, f"剧本缺少 genre 字段: {block_ids}"
        assert "episodes" in block_ids, f"剧本缺少 episodes 字段: {block_ids}"
        assert "logline" in block_ids, f"剧本缺少 logline 字段: {block_ids}"

    def test_storyboard_definition(self):
        """分镜脚本节点应包含剧本输入与画幅设置"""
        node = next(n for n in DRAMA_NODES if n["type"] == "builtin:storyboard")
        assert node["label"] == "分镜脚本"
        block_ids = [b.get("id") or b.get("name") for b in node["sub_blocks"]]
        assert "script" in block_ids, f"分镜缺少 script 字段: {block_ids}"
        assert "aspect_ratio" in block_ids, f"分镜缺少 aspect_ratio 字段: {block_ids}"

    def test_tts_definition(self):
        """TTS 节点应包含文本、音色、语速等字段"""
        node = next(n for n in DRAMA_NODES if n["type"] == "builtin:tts")
        assert node["label"] == "文本转语音"
        block_ids = [b.get("id") or b.get("name") for b in node["sub_blocks"]]
        assert "text" in block_ids, f"TTS 缺少 text 字段: {block_ids}"
        assert "voice" in block_ids, f"TTS 缺少 voice 字段: {block_ids}"

    def test_each_node_has_at_least_one_output(self):
        """每个节点应至少有输出端口"""
        for node in DRAMA_NODES:
            assert len(node["outputs"]) >= 1, f"节点缺少输出: {node['type']}"


class TestRegisterDramaNodes:
    """测试短剧节点注册"""

    def test_register_returns_count(self):
        """注册函数应返回注册数量"""
        mock_registry = MagicMock()
        count = register_drama_nodes(mock_registry)
        assert count == len(DRAMA_NODES)

    def test_register_calls_registry_register(self):
        """应调用 registry.register 注册每个节点"""
        mock_registry = MagicMock()
        register_drama_nodes(mock_registry)
        assert mock_registry.register.call_count == len(DRAMA_NODES)

    def test_register_attaches_executors(self):
        """注册时应传递执行器"""
        mock_registry = MagicMock()
        register_drama_nodes(mock_registry)
        for call in mock_registry.register.call_args_list:
            args, kwargs = call
            assert args[1] is not None or kwargs.get("executor") is not None, "执行器未附加"


class TestDramaExecutors:
    """测试短剧节点执行器"""

    def test_get_drama_executors_returns_dict(self):
        """应返回执行器字典"""
        executors = get_drama_executors()
        assert isinstance(executors, dict)
        assert len(executors) == len(DRAMA_NODES)

    def test_executors_have_all_drama_types(self):
        """应包含所有短剧节点类型的执行器"""
        executors = get_drama_executors()
        for node in DRAMA_NODES:
            assert node["type"] in executors, f"缺少执行器: {node['type']}"

    @pytest.mark.asyncio
    async def test_exec_short_drama_script_success(self):
        """短剧剧本生成应返回剧本与大纲"""
        config = {"genre": "urban", "episodes": 12, "logline": "一个普通人的逆袭之路"}
        ctx = {}
        result = await exec_short_drama_script(config, ctx)
        assert result["status"] == "success"
        assert "output" in result
        assert "outline" in result["output"]

    @pytest.mark.asyncio
    async def test_exec_storyboard_success(self):
        """分镜脚本应生成分镜列表"""
        config = {"script": "第一幕：主角在雨中奔跑", "aspect_ratio": "9:16"}
        ctx = {}
        result = await exec_storyboard(config, ctx)
        assert result["status"] == "success"
        assert "output" in result
        assert "shots" in result["output"]

    @pytest.mark.asyncio
    async def test_exec_scene_gen_success(self):
        """场景画面生成应返回画面描述与生成提示词"""
        config = {"scene": "雨中奔跑的街道", "style": "cinematic"}
        ctx = {}
        result = await exec_scene_gen(config, ctx)
        assert result["status"] == "success"
        assert "output" in result
        assert "prompts" in result["output"]

    @pytest.mark.asyncio
    async def test_exec_voice_over_success(self):
        """配音生成应返回音频信息"""
        config = {"lines": "你好，世界！", "voice": "female", "language": "zh"}
        ctx = {}
        result = await exec_voice_over(config, ctx)
        assert result["status"] == "success"
        assert "output" in result
        assert "duration" in result["output"]

    @pytest.mark.asyncio
    async def test_exec_subtitle_gen_success(self):
        """字幕生成应返回字幕文件"""
        config = {"text": "你好，世界！", "language": "zh", "format": "srt"}
        ctx = {}
        result = await exec_subtitle_gen(config, ctx)
        assert result["status"] == "success"
        assert "output" in result
        # SRT 格式应包含时间戳
        assert "--> " in result["output"]["subtitle"]

    @pytest.mark.asyncio
    async def test_exec_video_compose_success(self):
        """视频合成应返回合成结果"""
        config = {"clips": "clip1.mp4, clip2.mp4", "transition": "fade", "resolution": "1080x1920"}
        ctx = {}
        result = await exec_video_compose(config, ctx)
        assert result["status"] == "success"
        assert "output" in result

    @pytest.mark.asyncio
    async def test_exec_video_publish_success(self):
        """视频发布应返回发布结果与链接"""
        config = {"platform": "douyin", "title": "测试短剧", "tags": "短剧,逆袭"}
        ctx = {}
        result = await exec_video_publish(config, ctx)
        assert result["status"] == "success"
        assert "output" in result
        assert "url" in result["output"]

    @pytest.mark.asyncio
    async def test_exec_tts_success(self):
        """TTS 应返回音频与时长"""
        mock_tts = MagicMock()
        mock_tts.synthesize = AsyncMock(return_value=b"audio_data")
        with patch("neurova.collaboration.neurflow.drama_nodes._get_tts_manager", return_value=mock_tts):
            config = {"text": "你好，世界！", "voice": "female", "language": "zh"}
            ctx = {}
            result = await exec_tts(config, ctx)
            assert result["status"] == "success"
            assert "output" in result
            assert "duration" in result["output"]

    @pytest.mark.asyncio
    async def test_exec_tts_without_tts(self):
        """无 TTS 时应返回错误"""
        with patch("neurova.collaboration.neurflow.drama_nodes._get_tts_manager", return_value=None):
            config = {"text": "你好，世界！", "voice": "female"}
            ctx = {}
            result = await exec_tts(config, ctx)
            assert result["status"] == "failed"
            assert "error" in result

    @pytest.mark.asyncio
    async def test_exec_short_drama_script_via_llm(self):
        """短剧剧本应调用 Agent 生成（当可用时）"""
        mock_agent = MagicMock()
        mock_agent.chat = AsyncMock(return_value="## 剧本\n第一集：相遇\n### 场景1：街头")
        with patch("neurova.collaboration.neurflow.drama_nodes._get_agent", return_value=mock_agent):
            config = {"genre": "romance", "episodes": 6, "logline": "校园爱情故事"}
            ctx = {}
            result = await exec_short_drama_script(config, ctx)
            assert result["status"] == "success"
            mock_agent.chat.assert_called_once()


class TestDramaTemplateIntegrity:
    """测试短剧模板引用的节点完整性"""

    def test_template_referenced_tts_exists(self):
        """media.py 模板引用的 tts 节点应存在"""
        executors = get_drama_executors()
        assert "builtin:tts" in executors, "模板引用的 tts 节点未定义执行器"

    def test_drama_platforms_include_douyin_tiktok(self):
        """视频发布节点应支持抖音/TikTok等平台"""
        node = next(n for n in DRAMA_NODES if n["type"] == "builtin:video-publish")
        platforms = []
        for block in node["sub_blocks"]:
            if (block.get("id") or block.get("name")) == "platform":
                platforms = block.get("options", [])
        assert platforms, "video-publish 缺少平台选项"
        assert any("抖音" in str(p) or "Douyin" in str(p) for p in platforms), "缺少抖音"
        assert any("TikTok" in str(p) for p in platforms), "缺少 TikTok"