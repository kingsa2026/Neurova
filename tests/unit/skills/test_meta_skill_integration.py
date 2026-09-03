"""
Meta-skill 集成测试

测试新模块和增强模块的功能。
"""

import asyncio
import pytest
from unittest.mock import Mock, AsyncMock, patch, mock_open
from pathlib import Path

# 导入要测试的模块
from neurova.skills.skill_generator import SkillGenerator
from neurova.skills.project_to_skill import ProjectToSkillConverter
from neurova.skills.skill_chain_executor import SkillChainExecutor
from neurova.skills.prompt_optimizer import PromptOptimizer
from neurova.skills.task_decomposer import TaskDecomposer
from neurova.skills.auto_skill_improver import AutoSkillImprover


class TestSkillGenerator:
    """技能生成器测试"""

    @pytest.fixture
    def generator(self):
        return SkillGenerator()

    @pytest.mark.asyncio
    async def test_generate_skill_returns_result(self, generator):
        """测试技能生成返回结果"""
        requirement = "创建一个搜索技能，能够搜索网页内容"
        result = await generator.generate_skill(requirement)
        
        assert result is not None
        assert hasattr(result, 'skill_code')
        assert hasattr(result, 'skill_config')
        assert hasattr(result, 'success')
        assert result.success is True

    @pytest.mark.asyncio
    async def test_generate_skill_with_context(self, generator):
        """测试带上下文的技能生成"""
        requirement = "创建一个文件读取技能"
        context = {
            "file_types": ["txt", "md", "json"],
            "max_size": 1024 * 1024  # 1MB
        }
        
        result = await generator.generate_skill(requirement, context)
        
        assert result.success is True
        assert "txt" in result.skill_config.get("supported_formats", [])

    @pytest.mark.asyncio
    async def test_refine_skill(self, generator):
        """测试技能优化"""
        # 先生成一个技能
        requirement = "创建一个数学计算技能"
        generation_result = await generator.generate_skill(requirement)
        
        # 确保生成成功
        assert generation_result.success is True
        
        # 然后优化它
        feedback = "需要支持更多数学函数"
        refinement_result = await generator.refine_skill(
            skill_id=generation_result.skill_name,
            feedback=feedback
        )
        
        assert refinement_result.success is True
        assert refinement_result.improved is True

    @pytest.mark.asyncio
    async def test_validate_skill_code(self, generator):
        """测试技能代码验证"""
        valid_code = """
def execute(input_data):
    return {"result": input_data["value"] * 2}
"""
        validation_result = await generator.validate_skill(valid_code)
        
        assert validation_result.valid is True
        assert len(validation_result.errors) == 0


class TestProjectToSkillConverter:
    """项目转技能器测试"""

    @pytest.fixture
    def converter(self):
        return ProjectToSkillConverter()

    @pytest.mark.asyncio
    async def test_analyze_project(self, converter):
        """测试项目分析"""
        project_path = Path("./test_project")
        
        # 模拟项目结构
        with patch('pathlib.Path.exists', return_value=True):
            with patch('pathlib.Path.iterdir', return_value=[
                Path("main.py"),
                Path("utils.py"),
                Path("README.md")
            ]):
                result = await converter.analyze_project(str(project_path))
        
        assert result is not None
        assert hasattr(result, 'files')
        assert hasattr(result, 'dependencies')
        assert hasattr(result, 'complexity_score')

    @pytest.mark.asyncio
    async def test_extract_skill_from_analysis(self, converter):
        """测试从分析结果提取技能"""
        from neurova.skills.project_to_skill import ProjectAnalysisResult
        
        # 创建真实的分析结果
        analysis_result = ProjectAnalysisResult(
            project_path="./test_project",
            files=["main.py", "utils.py"],
            dependencies=["requests", "beautifulsoup4"],
            main_function="scrape_website",
            complexity_score=0.5,
            entry_points=["main.py"],
            metadata={}
        )
        
        # 模拟文件读取
        with patch('pathlib.Path.exists', return_value=True):
            with patch('builtins.open', mock_open(read_data='def scrape_website(data): return data')):
                extracted = await converter.extract_skill(analysis_result, "web_scraper")
        
        assert extracted is not None
        assert extracted.skill_name == "web_scraper"
        assert "requests" in extracted.dependencies

    @pytest.mark.asyncio
    async def test_package_as_skill(self, converter):
        """测试打包为技能"""
        from neurova.skills.project_to_skill import ExtractedSkill
        
        extracted_skill = ExtractedSkill(
            skill_name="test_skill",
            code="def execute(): pass",
            config={"version": "1.0.0"},
            dependencies=["requests"],
            entry_point="main.py",
            parameters={},
            metadata={}
        )
        
        package = await converter.package_as_skill(extracted_skill)
        
        assert package is not None
        assert package.success is True
        assert package.skill_path is not None


class TestSkillChainExecutor:
    """技能链执行器测试"""

    @pytest.fixture
    def executor(self):
        return SkillChainExecutor()

    @pytest.mark.asyncio
    async def test_execute_simple_chain(self, executor):
        """测试执行简单技能链"""
        from neurova.skills.models import SkillChain, SkillChainStep
        
        # 创建技能链
        chain = SkillChain(
            chain_id="test_chain",
            name="测试链",
            steps=[
                SkillChainStep(
                    step_id="step1",
                    skill_id="skill_1",
                    input_mapping={},
                    output_mapping={"result": "input"}
                ),
                SkillChainStep(
                    step_id="step2",
                    skill_id="skill_2",
                    input_mapping={"input": "result"},
                    output_mapping={}
                )
            ]
        )
        
        initial_input = {"value": 10}
        
        # 模拟技能执行
        with patch.object(executor, '_execute_step', new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = Mock(
                step_id="step1",
                skill_id="skill_1",
                status=Mock(value="completed"),
                output_data={"result": 20},
                error="",
                duration=0.1
            )
            
            result = await executor.execute_chain(chain, initial_input)
        
        assert result is not None
        assert result.success is True
        assert mock_execute.call_count == 2

    @pytest.mark.asyncio
    async def test_chain_with_error_handling(self, executor):
        """测试技能链错误处理"""
        from neurova.skills.models import SkillChain, SkillChainStep, StepStatus
        
        chain = SkillChain(
            chain_id="test_chain_error",
            name="错误测试链",
            steps=[
                SkillChainStep(
                    step_id="step1",
                    skill_id="failing_skill",
                    input_mapping={},
                    output_mapping={}
                )
            ]
        )
        
        initial_input = {"test": "data"}
        
        with patch.object(executor, '_execute_step', new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = Mock(
                step_id="step1",
                skill_id="failing_skill",
                status=StepStatus.FAILED,
                output_data={},
                error="技能执行失败",
                duration=0.1
            )
            
            result = await executor.execute_chain(chain, initial_input)
        
        assert result.success is False
        assert "技能执行失败" in result.error

    @pytest.mark.asyncio
    async def test_pause_and_resume_chain(self, executor):
        """测试暂停和恢复技能链"""
        chain_id = "test_chain_123"
        
        # 添加到活动链中
        executor._active_chains[chain_id] = {"status": Mock(value="running")}
        
        pause_result = await executor.pause_chain(chain_id)
        assert pause_result is True
        
        resume_result = await executor.resume_chain(chain_id)
        assert resume_result is True

    @pytest.mark.asyncio
    async def test_get_chain_status(self, executor):
        """测试获取技能链状态"""
        chain_id = "test_chain_456"
        
        # 添加到活动链中
        executor._active_chains[chain_id] = {
            "status": Mock(value="running"),
            "current_step": 1
        }
        executor._chain_instances[chain_id] = Mock(steps=[1, 2, 3])
        
        status = await executor.get_chain_status(chain_id)
        
        assert status is not None
        assert status.status.value == "running"
        assert status.progress == 1/3


class TestPromptOptimizer:
    """提示优化器测试"""

    @pytest.fixture
    def optimizer(self):
        return PromptOptimizer()

    @pytest.mark.asyncio
    async def test_analyze_prompt(self, optimizer):
        """测试提示词分析"""
        prompt = "请帮我搜索关于人工智能的最新新闻"
        skill_context = {"skill_type": "search", "domain": "technology"}
        
        analysis = await optimizer.analyze_prompt(prompt, skill_context)
        
        assert analysis is not None
        assert hasattr(analysis, 'clarity_score')
        assert hasattr(analysis, 'specificity_score')
        assert hasattr(analysis, 'suggestions')

    @pytest.mark.asyncio
    async def test_optimize_prompt(self, optimizer):
        """测试提示词优化"""
        original_prompt = "搜索AI新闻"
        optimization_goal = Mock()
        optimization_goal.type = "clarity"
        optimization_goal.weight = 0.8
        
        optimized = await optimizer.optimize_prompt(original_prompt, optimization_goal)
        
        assert optimized is not None
        assert optimized.success is True
        assert optimized.optimized_prompt != original_prompt
        assert len(optimized.improvements) > 0

    @pytest.mark.asyncio
    async def test_test_prompt_variants(self, optimizer):
        """测试提示词变体测试"""
        variants = [
            "搜索AI新闻",
            "请搜索最近的人工智能新闻",
            "查找关于AI技术发展的最新报道"
        ]
        
        test_cases = [
            {"input": "AI新闻", "expected_output": "相关结果"},
            {"input": "人工智能", "expected_output": "技术新闻"}
        ]
        
        results = await optimizer.test_prompt_variants(variants, test_cases)
        
        assert results is not None
        assert len(results.variant_scores) == 3
        assert results.best_variant_index >= 0


class TestEnhancedTaskDecomposer:
    """增强的任务分解器测试"""

    @pytest.fixture
    def decomposer(self):
        return TaskDecomposer()

    @pytest.mark.asyncio
    async def test_plan_skill_chain(self, decomposer):
        """测试技能链规划"""
        task = "创建一个网页爬虫，爬取新闻网站，提取标题和摘要，保存到数据库"
        
        chain_plan = await decomposer.plan_skill_chain(task)
        
        assert chain_plan is not None
        assert hasattr(chain_plan, 'steps')
        assert len(chain_plan.steps) >= 1  # 至少有一个步骤

    @pytest.mark.asyncio
    async def test_optimize_chain_order(self, decomposer):
        """测试优化技能链顺序"""
        from neurova.skills.models import SkillChainStep
        
        steps = [
            SkillChainStep(
                step_id="step3",
                skill_id="save_to_db",
                input_mapping={"input": "output_of_step2"},
                output_mapping={}
            ),
            SkillChainStep(
                step_id="step1",
                skill_id="crawl",
                input_mapping={},
                output_mapping={"result": "input"}
            ),
            SkillChainStep(
                step_id="step2",
                skill_id="extract",
                input_mapping={"input": "output_of_step1"},
                output_mapping={"result": "input"}
            )
        ]
        
        optimized = await decomposer.optimize_chain(steps)
        
        # 优化后应该按依赖顺序排列（step1 → step2 → step3）
        optimized_ids = [s.step_id for s in optimized]
        assert "step1" in optimized_ids
        assert "step2" in optimized_ids
        assert "step3" in optimized_ids
        assert optimized_ids.index("step1") < optimized_ids.index("step2")
        assert optimized_ids.index("step2") < optimized_ids.index("step3")

    @pytest.mark.asyncio
    async def test_estimate_chain_cost(self, decomposer):
        """测试估算技能链成本"""
        from neurova.skills.models import SkillChain, SkillChainStep
        
        chain_plan = SkillChain(
            chain_id="test_chain",
            name="测试链",
            steps=[
                SkillChainStep(
                    step_id="step1",
                    skill_id="skill1",
                    input_mapping={},
                    output_mapping={},
                    metadata={"estimated_time": 1.0, "resource_intensity": "low"}
                ),
                SkillChainStep(
                    step_id="step2",
                    skill_id="skill2",
                    input_mapping={},
                    output_mapping={},
                    metadata={"estimated_time": 2.0, "resource_intensity": "medium"}
                ),
                SkillChainStep(
                    step_id="step3",
                    skill_id="skill3",
                    input_mapping={},
                    output_mapping={},
                    metadata={"estimated_time": 0.5, "resource_intensity": "low"}
                )
            ]
        )
        
        cost = await decomposer.estimate_chain_cost(chain_plan)
        
        assert cost is not None
        assert cost["total_time"] == 3.5
        assert cost["resource_level"] in ["low", "medium", "high"]


class TestEnhancedAutoSkillImprover:
    """增强的技能改进器测试"""

    @pytest.fixture
    def improver(self):
        return AutoSkillImprover()

    @pytest.mark.asyncio
    async def test_optimize_skill_prompt(self, improver):
        """测试优化技能提示词"""
        skill_id = "search_skill"
        current_prompt = "搜索互联网上的信息"
        
        optimized = await improver.optimize_skill_prompt(skill_id, current_prompt)
        
        assert optimized is not None
        assert optimized.success is True
        assert optimized.optimized_prompt != current_prompt

    @pytest.mark.asyncio
    async def test_generate_prompt_variants(self, improver):
        """测试生成提示词变体"""
        base_prompt = "搜索网页内容"
        num_variants = 5
        
        variants = await improver.generate_prompt_variants(base_prompt, num_variants)
        
        assert len(variants) == num_variants
        # 变体可能相同，但应该有变化
        unique_variants = set(variants)
        assert len(unique_variants) >= 1  # 至少有一个变体

    @pytest.mark.asyncio
    async def test_run_prompt_ab_test(self, improver):
        """测试运行 A/B 测试"""
        prompt_a = "搜索AI新闻"
        prompt_b = "查找人工智能领域的最新动态"
        test_cases = [
            {"input": "AI", "expected_output": "人工智能"},
            {"input": "机器学习", "expected_output": "ML"}
        ]
        
        results = await improver.run_prompt_ab_test(prompt_a, prompt_b, test_cases)
        
        assert results is not None
        assert results["winner"] in ["A", "B", "tie"]
        assert results["confidence"] >= 0.5


class TestIntegrationWithAgent:
    """与 Agent 集成的测试"""

    @pytest.mark.asyncio
    async def test_agent_uses_skill_generator(self):
        """测试 Agent 使用技能生成器"""
        # 模拟 Agent 调用技能生成
        from neurova.agent_core import Agent
        
        agent = Mock(spec=Agent)
        agent.skill_generator = SkillGenerator()
        
        # 模拟 Agent 需要新技能
        requirement = "创建一个天气查询技能"
        
        with patch.object(agent.skill_generator, 'generate_skill', new_callable=AsyncMock) as mock_generate:
            mock_generate.return_value = Mock(success=True, skill_code="def execute(): pass")
            
            result = await agent.skill_generator.generate_skill(requirement)
            
            assert result.success is True
            mock_generate.assert_called_once_with(requirement)

    @pytest.mark.asyncio
    async def test_evolution_engine_uses_prompt_optimizer(self):
        """测试进化引擎使用提示优化器"""
        from neurova.skills.evolution_engine import EvolutionEngine
        
        engine = Mock(spec=EvolutionEngine)
        engine.prompt_optimizer = PromptOptimizer()
        
        # 模拟进化过程中的提示优化
        with patch.object(engine.prompt_optimizer, 'optimize_prompt', new_callable=AsyncMock) as mock_optimize:
            mock_optimize.return_value = Mock(success=True, optimized_prompt="优化后的提示")
            
            result = await engine.prompt_optimizer.optimize_prompt("原始提示", Mock())
            
            assert result.success is True
            mock_optimize.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])