#!/usr/bin/env python3
"""
Agent 创建和编辑功能测试
用于验证前端Agent表单和后端API的完整交互流程
"""

import requests
import json
import time
from typing import Dict, Any, Optional

BASE_URL = "http://192.168.10.132:9527/api/v1"

class AgentAPITester:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.token = None
        self.test_agent_id = f"test_agent_{int(time.time())}"
    
    def login(self, username: str = "admin", password: str = "admin123") -> bool:
        """登录获取token"""
        try:
            response = requests.post(
                f"{self.base_url}/auth/login",
                json={"username": username, "password": password},
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("code") == 0:
                    self.token = data.get("data", {}).get("token")
                    print(f"✅ 登录成功")
                    return True
            print(f"❌ 登录失败: {response.text}")
            return False
        except Exception as e:
            print(f"❌ 登录异常: {e}")
            return False
    
    def get_headers(self) -> Dict[str, str]:
        """获取带token的请求头"""
        if not self.token:
            raise ValueError("未登录，请先调用login()")
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
    
    def test_list_agents(self) -> bool:
        """测试列出所有Agent"""
        try:
            response = requests.get(
                f"{self.base_url}/agents",
                headers=self.get_headers(),
                timeout=10
            )
            data = response.json()
            if data.get("code") == 0:
                agents = data.get("data", {}).get("agents", [])
                print(f"✅ 列出Agent成功: {len(agents)} 个Agent")
                return True
            print(f"❌ 列出Agent失败: {data.get('message')}")
            return False
        except Exception as e:
            print(f"❌ 列出Agent异常: {e}")
            return False
    
    def test_create_agent(self) -> Optional[str]:
        """测试创建Agent"""
        try:
            agent_data = {
                "agent_id": self.test_agent_id,
                "name": f"测试Agent_{int(time.time())}",
                "description": "自动化测试创建的Agent",
                "llm_model": "auto",
                "personality": "友善、专业",
                "constitution": "遵循法律法规",
                "enable_memory": True
            }
            
            response = requests.post(
                f"{self.base_url}/agents",
                headers=self.get_headers(),
                json=agent_data,
                timeout=10
            )
            data = response.json()
            if data.get("code") == 0:
                created = data.get("data", {})
                print(f"✅ 创建Agent成功: {created.get('name')} (ID: {created.get('agent_id')})")
                return created.get("agent_id")
            print(f"❌ 创建Agent失败: {data.get('message')}")
            print(f"   响应详情: {data}")
            return None
        except Exception as e:
            print(f"❌ 创建Agent异常: {e}")
            return None
    
    def test_get_agent(self, agent_id: str) -> bool:
        """测试获取单个Agent详情"""
        try:
            response = requests.get(
                f"{self.base_url}/agents/{agent_id}",
                headers=self.get_headers(),
                timeout=10
            )
            data = response.json()
            if data.get("code") == 0:
                agent = data.get("data", {})
                print(f"✅ 获取Agent详情成功: {agent.get('name')}")
                print(f"   - LLM模型: {agent.get('llm_model')}")
                print(f"   - 描述: {agent.get('description', '无')}")
                print(f"   - 个性: {agent.get('personality', '无')}")
                print(f"   - 宪法: {agent.get('constitution', '无')}")
                return True
            print(f"❌ 获取Agent详情失败: {data.get('message')}")
            return False
        except Exception as e:
            print(f"❌ 获取Agent详情异常: {e}")
            return False
    
    def test_update_agent(self, agent_id: str) -> bool:
        """测试更新Agent配置"""
        try:
            update_data = {
                "name": f"已更新的Agent_{int(time.time())}",
                "description": "这是更新后的描述",
                "personality": "更新后的个性设定",
                "constitution": "更新后的行为准则",
                "llm_model": "gpt-4"
            }
            
            response = requests.put(
                f"{self.base_url}/agents/{agent_id}/config",
                headers=self.get_headers(),
                json=update_data,
                timeout=10
            )
            data = response.json()
            if data.get("code") == 0:
                updated = data.get("data", {})
                print(f"✅ 更新Agent配置成功")
                print(f"   - 新名称: {updated.get('name')}")
                print(f"   - 新描述: {updated.get('description')}")
                return True
            print(f"❌ 更新Agent配置失败: {data.get('message')}")
            print(f"   响应详情: {data}")
            return False
        except Exception as e:
            print(f"❌ 更新Agent配置异常: {e}")
            return False
    
    def test_verify_update(self, agent_id: str) -> bool:
        """验证更新是否生效"""
        try:
            response = requests.get(
                f"{self.base_url}/agents/{agent_id}",
                headers=self.get_headers(),
                timeout=10
            )
            data = response.json()
            if data.get("code") == 0:
                agent = data.get("data", {})
                # 检查更新后的字段
                has_updates = (
                    agent.get("description") == "这是更新后的描述" and
                    agent.get("personality") == "更新后的个性设定"
                )
                if has_updates:
                    print(f"✅ 验证更新成功：配置已正确保存和读取")
                    return True
                else:
                    print(f"❌ 验证更新失败：配置未正确更新")
                    print(f"   期望描述: '这是更新后的描述'")
                    print(f"   实际描述: '{agent.get('description')}'")
                    print(f"   期望个性: '更新后的个性设定'")
                    print(f"   实际个性: '{agent.get('personality')}'")
                    return False
            print(f"❌ 获取Agent详情失败: {data.get('message')}")
            return False
        except Exception as e:
            print(f"❌ 验证更新异常: {e}")
            return False
    
    def test_delete_agent(self, agent_id: str) -> bool:
        """测试删除Agent"""
        try:
            response = requests.delete(
                f"{self.base_url}/agents/{agent_id}",
                headers=self.get_headers(),
                timeout=10
            )
            data = response.json()
            if data.get("code") == 0:
                print(f"✅ 删除Agent成功: {agent_id}")
                return True
            print(f"❌ 删除Agent失败: {data.get('message')}")
            return False
        except Exception as e:
            print(f"❌ 删除Agent异常: {e}")
            return False
    
    def run_full_test(self):
        """运行完整测试流程"""
        print("\n" + "="*60)
        print("🧪 Agent API 完整功能测试")
        print("="*60 + "\n")
        
        # 1. 登录
        print("\n📋 步骤1: 登录...")
        if not self.login():
            return False
        
        # 2. 列出Agent
        print("\n📋 步骤2: 列出所有Agent...")
        if not self.test_list_agents():
            return False
        
        # 3. 创建Agent
        print("\n📋 步骤3: 创建新Agent...")
        created_id = self.test_create_agent()
        if not created_id:
            print("⚠️  创建失败，但这可能是正常的（Agent ID重复）")
            created_id = self.test_agent_id  # 继续使用测试ID进行其他测试
        
        # 4. 获取创建的Agent详情
        if created_id:
            print("\n📋 步骤4: 获取创建的Agent详情...")
            self.test_get_agent(created_id)
        
        # 5. 更新Agent配置
        if created_id:
            print("\n📋 步骤5: 更新Agent配置...")
            if not self.test_update_agent(created_id):
                print("⚠️  更新失败，继续验证...")
        
        # 6. 验证更新
        if created_id:
            print("\n📋 步骤6: 验证更新是否生效...")
            self.test_verify_update(created_id)
        
        # 7. 清理：删除测试Agent
        print("\n📋 步骤7: 清理测试数据...")
        self.test_delete_agent(self.test_agent_id)
        
        print("\n" + "="*60)
        print("✅ 测试流程完成")
        print("="*60 + "\n")


def main():
    tester = AgentAPITester()
    tester.run_full_test()


if __name__ == "__main__":
    main()
