"""任务分解器（TaskDecomposer）测试。

P1-13（全库断点审计 2026-11-12，拍板：退役）：本文件原为"元技能七模块"集成测试；
skill_generator / project_to_skill / skill_chain_executor / prompt_optimizer /
auto_skill_improver 均为零生产消费方的死码，已按教义第 7 条退役，对应测试类随批摘除。
TaskDecomposer 仍被 agent_skill_manager / skill_need_analyzer 消费（在役），其测试保留。
"""

import pytest

from neurova.skills.task_decomposer import TaskDecomposer


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
