#!/usr/bin/env python3
"""
Neurova CLI 聊天客户端
=====================

交互式命令行界面，支持：
- 聊天对话
- /agent 命令管理 Agent
- /llm 命令管理 LLM 模型
- Ctrl+C 退出
"""

import argparse
import json
import os
import sys
import textwrap
from typing import Optional

import httpx

# 默认配置
DEFAULT_BASE_URL = "http://localhost:9527"
API_PREFIX = "/api/v1"


class NeurovaCLI:
    """Neurova CLI 聊天客户端"""

    def __init__(self, base_url: str = DEFAULT_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.api_url = f"{self.base_url}{API_PREFIX}"
        self.token: Optional[str] = None
        self.current_agent_id: Optional[str] = None
        self.running = True

    def _headers(self) -> dict:
        """获取请求头"""
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _get(self, path: str, **kwargs) -> dict:
        """GET 请求"""
        url = f"{self.api_url}{path}"
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(url, headers=self._headers(), **kwargs)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as e:
            print(f"\033[91m[错误] {e.response.status_code}: {e.response.text}\033[0m")
            return {}
        except Exception as e:
            print(f"\033[91m[错误] 请求失败: {e}\033[0m")
            return {}

    def _post(self, path: str, **kwargs) -> dict:
        """POST 请求"""
        url = f"{self.api_url}{path}"
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.post(url, headers=self._headers(), **kwargs)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as e:
            print(f"\033[91m[错误] {e.response.status_code}: {e.response.text}\033[0m")
            return {}
        except Exception as e:
            print(f"\033[91m[错误] 请求失败: {e}\033[0m")
            return {}

    def _delete(self, path: str, **kwargs) -> dict:
        """DELETE 请求"""
        url = f"{self.api_url}{path}"
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.delete(url, headers=self._headers(), **kwargs)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as e:
            print(f"\033[91m[错误] {e.response.status_code}: {e.response.text}\033[0m")
            return {}
        except Exception as e:
            print(f"\033[91m[错误] 请求失败: {e}\033[0m")
            return {}

    def login(self, username: str = "admin", password: str = "admin") -> bool:
        """登录获取 token"""
        try:
            with httpx.Client(timeout=10) as client:
                # 尝试多个可能的登录路径
                login_paths = [
                    f"{self.api_url}/auth/login",
                    f"{self.base_url}/api/v1/auth/login",
                    f"{self.base_url}/v1/auth/login",
                ]
                
                for path in login_paths:
                    try:
                        resp = client.post(
                            path,
                            json={"username": username, "password": password},
                        )
                        if resp.status_code == 200:
                            data = resp.json()
                            self.token = data.get("access_token")
                            return True
                    except Exception:
                        continue
                
                print(f"\033[91m[错误] 登录失败，请检查服务器配置\033[0m")
                return False
        except Exception as e:
            print(f"\033[91m[错误] 无法连接到服务器: {e}\033[0m")
            return False

    def check_health(self) -> bool:
        """检查服务器健康状态"""
        try:
            with httpx.Client(timeout=5) as client:
                resp = client.get(f"{self.base_url}/health")
                return resp.status_code == 200
        except Exception:
            return False

    # ==================== Agent 命令 ====================

    def list_agents(self):
        """列出所有 Agent"""
        data = self._get("/agents")
        if not data:
            print("\033[93m[提示] 没有找到 Agent\033[0m")
            return

        print("\n\033[1m┌─────────────────────────────────────────────────────────────┐\033[0m")
        print("\033[1m│  Agent 列表                                                 │\033[0m")
        print("\033[1m├─────────────────────────────────────────────────────────────┤\033[0m")

        for i, agent in enumerate(data):
            agent_id = agent.get("agent_id", "unknown")
            name = agent.get("name", "Unknown")
            status = agent.get("status", "unknown")
            model = agent.get("model", "N/A")

            # 当前选中标记
            marker = "►" if agent_id == self.current_agent_id else " "

            # 状态颜色
            status_color = "\033[92m" if status == "running" else "\033[93m" if status == "config_only" else "\033[91m"

            print(f"\033[1m│\033[0m {marker} \033[1m{i+1}.\033[0m {name:<20} ID: {agent_id:<12} 状态: {status_color}{status}\033[0m 模型: {model}")

        print("\033[1m└─────────────────────────────────────────────────────────────┘\033[0m")
        print("\n\033[90m提示: 输入序号切换 Agent，或使用 /agent switch <序号>\033[0m")

    def switch_agent(self, index: int):
        """切换 Agent"""
        data = self._get("/agents")
        if not data or index < 1 or index > len(data):
            print(f"\033[91m[错误] 无效的序号: {index}\033[0m")
            return

        agent = data[index - 1]
        agent_id = agent.get("agent_id")
        name = agent.get("name")

        self.current_agent_id = agent_id
        print(f"\033[92m[✓] 已切换到 Agent: {name} (ID: {agent_id})\033[0m")

    def create_agent(self):
        """交互式创建 Agent"""
        print("\n\033[1m┌─────────────────────────────────────────────────────────────┐\033[0m")
        print("\033[1m│  创建新 Agent                                                │\033[0m")
        print("\033[1m└─────────────────────────────────────────────────────────────┘\033[0m")

        name = input("\033[1mAgent 名称:\033[0m ").strip()
        if not name:
            print("\033[91m[错误] 名称不能为空\033[0m")
            return

        description = input("\033[1m描述 (可选):\033[0m ").strip()
        enable_memory = input("\033[1m启用记忆? (Y/n):\033[0m ").strip().lower() != "n"

        # 创建 Agent
        payload = {
            "name": name,
            "description": description,
            "enable_memory": enable_memory,
        }

        result = self._post("/agents", json=payload)
        if result:
            agent_id = result.get("agent_id")
            print(f"\033[92m[✓] Agent 创建成功: {name} (ID: {agent_id})\033[0m")

            # 自动切换到新创建的 Agent
            switch = input("\033[1m是否切换到新 Agent? (Y/n):\033[0m ").strip().lower()
            if switch != "n":
                self.current_agent_id = agent_id
                print(f"\033[92m[✓] 已切换到 Agent: {name}\033[0m")

    def delete_agent(self):
        """交互式删除 Agent"""
        data = self._get("/agents")
        if not data:
            print("\033[93m[提示] 没有可删除的 Agent\033[0m")
            return

        # 列出 Agent
        self.list_agents()

        try:
            index = int(input("\n\033[1m输入要删除的 Agent 序号:\033[0m ").strip())
        except ValueError:
            print("\033[91m[错误] 请输入有效数字\033[0m")
            return

        if index < 1 or index > len(data):
            print(f"\033[91m[错误] 无效的序号: {index}\033[0m")
            return

        agent = data[index - 1]
        agent_id = agent.get("agent_id")
        name = agent.get("name")

        # 确认删除
        confirm = input(f"\033[93m[警告] 确定要删除 Agent '{name}'? (y/N):\033[0m ").strip().lower()
        if confirm != "y":
            print("\033[90m[取消] 删除操作已取消\033[0m")
            return

        result = self._delete(f"/agents/{agent_id}")
        if result is not None:
            print(f"\033[92m[✓] Agent '{name}' 已删除\033[0m")

            # 如果删除的是当前 Agent，清除选择
            if self.current_agent_id == agent_id:
                self.current_agent_id = None
                print("\033[93m[提示] 当前 Agent 已删除，请选择其他 Agent\033[0m")

    def handle_agent_command(self, args: list):
        """处理 /agent 命令"""
        if not args:
            self.list_agents()
            return

        subcmd = args[0].lower()

        if subcmd == "add":
            self.create_agent()
        elif subcmd == "del" or subcmd == "delete":
            self.delete_agent()
        elif subcmd == "switch":
            if len(args) < 2:
                print("\033[91m[错误] 用法: /agent switch <序号>\033[0m")
                return
            try:
                index = int(args[1])
                self.switch_agent(index)
            except ValueError:
                print("\033[91m[错误] 请输入有效数字\033[0m")
        else:
            # 尝试解析为序号
            try:
                index = int(subcmd)
                self.switch_agent(index)
            except ValueError:
                print("\033[91m[错误] 未知命令。用法: /agent [add|del|switch|<序号>]\033[0m")

    # ==================== LLM 命令 ====================

    def list_providers(self):
        """列出所有 LLM 服务商"""
        data = self._get("/providers")
        if not data:
            print("\033[93m[提示] 没有找到 LLM 服务商\033[0m")
            return

        print("\n\033[1m┌─────────────────────────────────────────────────────────────┐\033[0m")
        print("\033[1m│  LLM 服务商列表                                              │\033[0m")
        print("\033[1m├─────────────────────────────────────────────────────────────┤\033[0m")

        for i, provider in enumerate(data):
            provider_id = provider.get("provider_id", "unknown")
            name = provider.get("name", "Unknown")
            ptype = provider.get("provider_type", "unknown")
            status = provider.get("status", "unknown")
            is_active = provider.get("is_active", False)
            models_count = provider.get("models_count", 0)

            # 活跃状态标记
            marker = "►" if is_active else " "

            # 状态颜色
            status_color = "\033[92m" if status == "connected" else "\033[91m"

            print(f"\033[1m│\033[0m {marker} \033[1m{i+1}.\033[0m {name:<20} 类型: {ptype:<12} 状态: {status_color}{status}\033[0m 模型数: {models_count}")

        print("\033[1m└─────────────────────────────────────────────────────────────┘\033[0m")

        # 获取当前活跃模型
        active = self._get("/providers/active-model")
        if active:
            print(f"\n\033[1m当前活跃模型:\033[0m {active.get('model_id', 'N/A')} ({active.get('provider_name', 'N/A')})")

        print("\n\033[90m提示: 输入序号切换服务商，或使用 /llm switch <序号>\033[0m")

    def switch_provider(self, index: int):
        """切换 LLM 服务商/模型"""
        data = self._get("/providers")
        if not data or index < 1 or index > len(data):
            print(f"\033[91m[错误] 无效的序号: {index}\033[0m")
            return

        provider = data[index - 1]
        provider_id = provider.get("provider_id")
        name = provider.get("name")

        # 获取该服务商的模型列表
        models_data = self._get(f"/providers/{provider_id}/models/discover")
        if not models_data:
            print(f"\033[93m[提示] 服务商 '{name}' 没有可用模型\033[0m")
            return

        models = models_data if isinstance(models_data, list) else models_data.get("models", [])
        if not models:
            print(f"\033[93m[提示] 服务商 '{name}' 没有可用模型\033[0m")
            return

        print(f"\n\033[1m┌─────────────────────────────────────────────────────────────┐\033[0m")
        print(f"\033[1m│  {name} - 模型列表                                           │\033[0m")
        print(f"\033[1m├─────────────────────────────────────────────────────────────┤\033[0m")

        for i, model in enumerate(models):
            model_id = model if isinstance(model, str) else model.get("model_id", "unknown")
            print(f"\033[1m│\033[0m   \033[1m{i+1}.\033[0m {model_id}")

        print(f"\033[1m└─────────────────────────────────────────────────────────────┘\033[0m")

        try:
            model_index = int(input("\n\033[1m选择模型序号:\033[0m ").strip())
        except ValueError:
            print("\033[91m[错误] 请输入有效数字\033[0m")
            return

        if model_index < 1 or model_index > len(models):
            print(f"\033[91m[错误] 无效的序号: {model_index}\033[0m")
            return

        model_id = models[model_index - 1] if isinstance(models[model_index - 1], str) else models[model_index - 1].get("model_id")

        # 激活模型
        result = self._post("/providers/activate-model", json={
            "provider_id": provider_id,
            "model_id": model_id,
        })
        if result:
            print(f"\033[92m[✓] 已切换到模型: {model_id} ({name})\033[0m")

    def create_provider(self):
        """交互式创建 LLM 服务商"""
        print("\n\033[1m┌─────────────────────────────────────────────────────────────┐\033[0m")
        print("\033[1m│  添加 LLM 服务商                                             │\033[0m")
        print("\033[1m└─────────────────────────────────────────────────────────────┘\033[0m")

        print("\n\033[1m支持的服务商类型:\033[0m")
        print("  1. openai      - OpenAI / 兼容 API")
        print("  2. anthropic   - Anthropic Claude")
        print("  3. gemini      - Google Gemini")
        print("  4. ollama      - Ollama 本地模型")
        print("  5. openrouter  - OpenRouter")

        type_choice = input("\n\033[1m选择服务商类型 (1-5):\033[0m ").strip()
        type_map = {"1": "openai", "2": "anthropic", "3": "gemini", "4": "ollama", "5": "openrouter"}
        provider_type = type_map.get(type_choice)
        if not provider_type:
            print("\033[91m[错误] 无效的选择\033[0m")
            return

        name = input("\033[1m服务商名称:\033[0m ").strip()
        if not name:
            print("\033[91m[错误] 名称不能为空\033[0m")
            return

        # 根据类型设置默认 URL
        default_urls = {
            "openai": "https://api.openai.com/v1",
            "anthropic": "https://api.anthropic.com",
            "gemini": "https://generativelanguage.googleapis.com",
            "ollama": "http://localhost:11434",
            "openrouter": "https://openrouter.ai/api/v1",
        }

        base_url = input(f"\033[1mAPI URL [{default_urls[provider_type]}]:\033[0m ").strip()
        if not base_url:
            base_url = default_urls[provider_type]

        api_key = ""
        if provider_type != "ollama":
            api_key = input("\033[1mAPI Key:\033[0m ").strip()
            if not api_key:
                print("\033[93m[警告] 未提供 API Key，连接可能失败\033[0m")

        # 创建服务商
        payload = {
            "name": name,
            "provider_type": provider_type,
            "base_url": base_url,
            "api_key": api_key,
        }

        result = self._post("/providers", json=payload)
        if result:
            provider_id = result.get("provider_id")
            print(f"\033[92m[✓] 服务商创建成功: {name} (ID: {provider_id})\033[0m")

            # 询问是否立即测试连接
            test = input("\033[1m是否测试连接? (Y/n):\033[0m ").strip().lower()
            if test != "n":
                test_result = self._post(f"/providers/{provider_id}/check-connection")
                if test_result and test_result.get("connected"):
                    print(f"\033[92m[✓] 连接成功\033[0m")
                else:
                    print(f"\033[91m[✗] 连接失败\033[0m")

    def delete_provider(self):
        """交互式删除 LLM 服务商"""
        data = self._get("/providers")
        if not data:
            print("\033[93m[提示] 没有可删除的服务商\033[0m")
            return

        # 列出服务商
        self.list_providers()

        try:
            index = int(input("\n\033[1m输入要删除的服务商序号:\033[0m ").strip())
        except ValueError:
            print("\033[91m[错误] 请输入有效数字\033[0m")
            return

        if index < 1 or index > len(data):
            print(f"\033[91m[错误] 无效的序号: {index}\033[0m")
            return

        provider = data[index - 1]
        provider_id = provider.get("provider_id")
        name = provider.get("name")

        # 确认删除
        confirm = input(f"\033[93m[警告] 确定要删除服务商 '{name}'? (y/N):\033[0m ").strip().lower()
        if confirm != "y":
            print("\033[90m[取消] 删除操作已取消\033[0m")
            return

        result = self._delete(f"/providers/{provider_id}")
        if result is not None:
            print(f"\033[92m[✓] 服务商 '{name}' 已删除\033[0m")

    def handle_llm_command(self, args: list):
        """处理 /llm 命令"""
        if not args:
            self.list_providers()
            return

        subcmd = args[0].lower()

        if subcmd == "add":
            self.create_provider()
        elif subcmd == "del" or subcmd == "delete":
            self.delete_provider()
        elif subcmd == "switch":
            if len(args) < 2:
                print("\033[91m[错误] 用法: /llm switch <序号>\033[0m")
                return
            try:
                index = int(args[1])
                self.switch_provider(index)
            except ValueError:
                print("\033[91m[错误] 请输入有效数字\033[0m")
        else:
            # 尝试解析为序号
            try:
                index = int(subcmd)
                self.switch_provider(index)
            except ValueError:
                print("\033[91m[错误] 未知命令。用法: /llm [add|del|switch|<序号>]\033[0m")

    # ==================== 聊天功能 ====================

    def send_message(self, message: str):
        """发送消息并获取回复"""
        if not self.current_agent_id:
            print("\033[93m[提示] 请先选择一个 Agent (使用 /agent 命令)\033[0m")
            return

        payload = {
            "message": message,
            "agent_id": self.current_agent_id,
        }

        try:
            print("\033[90m[思考中...]\033[0m", end="", flush=True)

            with httpx.Client(timeout=120) as client:
                resp = client.post(
                    f"{self.api_url}/chat",
                    json=payload,
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()

                # 清除"思考中"提示
                print("\r" + " " * 20 + "\r", end="")

                # 输出回复
                reply = data.get("response") or data.get("message") or data.get("content", "")
                if reply:
                    print(f"\n\033[96m[Neurova]\033[0m {reply}\n")
                else:
                    print(f"\n\033[93m[提示] 收到空回复\033[0m\n")

        except httpx.HTTPStatusError as e:
            print(f"\r\033[91m[错误] {e.response.status_code}: {e.response.text}\033[0m")
        except Exception as e:
            print(f"\r\033[91m[错误] 请求失败: {e}\033[0m")

    def show_help(self):
        """显示帮助信息"""
        print("""
\033[1m┌─────────────────────────────────────────────────────────────┐\033[0m
\033[1m│  Neurova CLI 命令帮助                                        │\033[0m
\033[1m├─────────────────────────────────────────────────────────────┤\033[0m
\033[1m│\033[0m                                                             \033[1m│\033[0m
\033[1m│\033[0m  \033[1m/agent\033[0m              列出所有 Agent                        \033[1m│\033[0m
\033[1m│\033[0m  \033[1m/agent add\033[0m           创建新 Agent                          \033[1m│\033[0m
\033[1m│\033[0m  \033[1m/agent del\033[0m           删除 Agent                            \033[1m│\033[0m
\033[1m│\033[0m  \033[1m/agent switch <N>\033[0m    切换到第 N 个 Agent                   \033[1m│\033[0m
\033[1m│\033[0m  \033[1m/agent <N>\033[0m           同上，快捷方式                         \033[1m│\033[0m
\033[1m│\033[0m                                                             \033[1m│\033[0m
\033[1m│\033[0m  \033[1m/llm\033[0m                列出所有 LLM 服务商                    \033[1m│\033[0m
\033[1m│\033[0m  \033[1m/llm add\033[0m             添加 LLM 服务商                       \033[1m│\033[0m
\033[1m│\033[0m  \033[1m/llm del\033[0m             删除 LLM 服务商                       \033[1m│\033[0m
\033[1m│\033[0m  \033[1m/llm switch <N>\033[0m      切换到第 N 个服务商                   \033[1m│\033[0m
\033[1m│\033[0m  \033[1m/llm <N>\033[0m             同上，快捷方式                         \033[1m│\033[0m
\033[1m│\033[0m                                                             \033[1m│\033[0m
\033[1m│\033[0m  \033[1m/help\033[0m                显示此帮助信息                         \033[1m│\033[0m
\033[1m│\033[0m  \033[1m/clear\033[0m               清屏                                  \033[1m│\033[0m
\033[1m│\033[0m  \033[1m/exit\033[0m 或 \033[1mCtrl+C\033[0m      退出程序                              \033[1m│\033[0m
\033[1m│\033[0m                                                             \033[1m│\033[0m
\033[1m└─────────────────────────────────────────────────────────────┘\033[0m
""")

    def run(self):
        """主循环"""
        print("""
\033[1m╔═══════════════════════════════════════════════════════════════╗\033[0m
\033[1m║                                                               ║\033[0m
\033[1m║   ███╗   ██╗███████╗██╗   ██╗██████╗  ██████╗ ██╗   ██╗      ║\033[0m
\033[1m║   ████╗  ██║██╔════╝██║   ██║██╔══██╗██╔═══██╗██║   ██║      ║\033[0m
\033[1m║   ██╔██╗ ██║█████╗  ██║   ██║██████╔╝██║   ██║██║   ██║      ║\033[0m
\033[1m║   ██║╚██╗██║██╔══╝  ██║   ██║██╔══██╗██║   ██║╚██╗ ██╔╝      ║\033[0m
\033[1m║   ██║ ╚████║███████╗╚██████╔╝██║  ██║╚██████╔╝ ╚████╔╝       ║\033[0m
\033[1m║   ╚═╝  ╚═══╝╚══════╝ ╚═════╝ ╚═╝  ╚═╝ ╚═════╝   ╚═══╝        ║\033[0m
\033[1m║                                                               ║\033[0m
\033[1m║            智能无限，协作无间 - CLI 聊天客户端                  ║\033[0m
\033[1m║                                                               ║\033[0m
\033[1m╚═══════════════════════════════════════════════════════════════╝\033[0m
""")

        # 检查服务器连接
        print("\033[90m[连接] 正在检查服务器状态...\033[0m")
        if not self.check_health():
            print(f"\033[91m[错误] 无法连接到服务器: {self.base_url}\033[0m")
            print("\033[93m[提示] 请确保后端服务已启动 (python start_server.py)\033[0m")
            return

        print(f"\033[92m[✓] 服务器连接成功: {self.base_url}\033[0m")

        # 登录
        print("\033[90m[登录] 正在获取访问令牌...\033[0m")
        if not self.login():
            print("\033[91m[错误] 登录失败，请检查服务器配置\033[0m")
            return

        print("\033[92m[✓] 登录成功\033[0m")

        # 加载 Agent 列表
        agents = self._get("/agents")
        if agents:
            # 自动选择第一个 Agent
            self.current_agent_id = agents[0].get("agent_id")
            print(f"\033[92m[✓] 已选择 Agent: {agents[0].get('name')} (ID: {self.current_agent_id})\033[0m")

        print("\n\033[90m输入 /help 查看命令帮助，输入消息开始聊天，Ctrl+C 退出\033[0m\n")

        # 主循环
        while self.running:
            try:
                # 显示提示符
                agent_name = "未选择"
                if self.current_agent_id and agents:
                    for a in agents:
                        if a.get("agent_id") == self.current_agent_id:
                            agent_name = a.get("name", self.current_agent_id)
                            break

                prompt = f"\033[1m\033[92m[{agent_name}]\033[0m > "
                user_input = input(prompt).strip()

                if not user_input:
                    continue

                # 处理命令
                if user_input.startswith("/"):
                    parts = user_input.split()
                    cmd = parts[0].lower()
                    args = parts[1:]

                    if cmd == "/agent":
                        self.handle_agent_command(args)
                    elif cmd == "/llm":
                        self.handle_llm_command(args)
                    elif cmd == "/help":
                        self.show_help()
                    elif cmd == "/clear":
                        os.system("cls" if os.name == "nt" else "clear")
                    elif cmd == "/exit":
                        print("\033[90m再见！\033[0m")
                        self.running = False
                    else:
                        print(f"\033[91m[错误] 未知命令: {cmd}。输入 /help 查看帮助\033[0m")
                else:
                    # 发送消息
                    self.send_message(user_input)

            except KeyboardInterrupt:
                print("\n\n\033[90m再见！\033[0m")
                self.running = False
            except EOFError:
                print("\n\n\033[90m再见！\033[0m")
                self.running = False


def main():
    parser = argparse.ArgumentParser(description="Neurova CLI 聊天客户端")
    parser.add_argument("--url", default=DEFAULT_BASE_URL, help="服务器 URL")
    args = parser.parse_args()

    cli = NeurovaCLI(base_url=args.url)
    cli.run()


if __name__ == "__main__":
    main()
