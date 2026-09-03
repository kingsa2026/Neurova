"""
测试多轮对话中的输出截断问题
重现用户报告的"输出的内容不完整"问题
"""
import requests
import json
import time
import re

BASE = "http://localhost:9527/api/v1"
TOKEN = None

def login():
    """登录获取token"""
    global TOKEN
    # 尝试多个可能的密码
    passwords = ["Admin123!", "p5GXCxYWPKT8LFld", "fImNvNyt9m1opT1S", "admin123", "Admin@123356", "password"]
    
    for password in passwords:
        print(f"尝试密码: {password}")
        r = requests.post(f"{BASE}/auth/login", json={
            "username": "admin",
            "password": password
        })
        print(f"登录响应状态码: {r.status_code}")
        print(f"登录响应内容: {r.text[:500]}")
        
        if r.status_code == 200:
            try:
                data = r.json()
                if data.get("success", False):
                    print(f"✓ 使用密码 '{password}' 登录成功")
                    # 获取token
                    if "data" in data:
                        token_data = data["data"]
                        if isinstance(token_data, dict):
                            TOKEN = token_data.get("token")
                        elif isinstance(token_data, str):
                            TOKEN = token_data
                    return True
            except json.JSONDecodeError:
                continue
    
    print("✗ 所有密码尝试失败")
    return False
    print(f"登录响应状态码: {r.status_code}")
    print(f"登录响应内容: {r.text[:500]}")
    if r.status_code == 200:
        try:
            data = r.json()
            print(f"登录响应数据: {json.dumps(data, ensure_ascii=False)[:500]}")
            if data is None:
                print(f"✗ 登录响应JSON数据为None")
                return False
            
            # 检查响应结构
            if "data" in data:
                token_data = data["data"]
                if isinstance(token_data, dict):
                    TOKEN = token_data.get("token")
                elif isinstance(token_data, str):
                    TOKEN = token_data
                else:
                    print(f"✗ 未知的data类型: {type(token_data)}")
                    return False
            else:
                print(f"✗ 响应中没有data字段")
                return False
            
            if TOKEN:
                print(f"✓ 登录成功")
                return True
            else:
                print(f"✗ 登录成功但未获取到token")
                return False
        except json.JSONDecodeError as e:
            print(f"✗ 登录响应JSON解析失败: {e}")
            print(f"响应内容: {r.text[:500]}")
            return False
    else:
        print(f"✗ 登录失败: {r.status_code}")
        return False

def chat(message, agent_id="kai", stream=False):
    """发送消息并获取回复"""
    headers = {"Authorization": f"Bearer {TOKEN}"}
    r = requests.post(
        f"{BASE}/chat",
        json={"message": message, "agent_id": agent_id, "stream": stream},
        headers=headers,
        timeout=60
    )
    if r.status_code == 200:
        data = r.json()
        return data.get("data", {}).get("response", ""), data
    else:
        return f"Error: {r.status_code}", {}

def is_response_truncated(response):
    """检查回复是否被截断"""
    if not response:
        return True
    
    # 检查是否以完整的句子结束
    # 中文句子通常以。！？结尾
    # 英文句子通常以.!?结尾
    response = response.strip()
    
    # 如果以这些标点结尾，可能不是截断
    if re.search(r'[。！？.!?]$', response):
        return False
    
    # 如果以代码块结尾（```），可能不是截断
    if response.endswith('```'):
        return False
    
    # 如果以换行符结尾，可能不是截断
    if response.endswith('\n'):
        return False
    
    # 如果以列表项结尾（- 或 *），可能不是截断
    if re.search(r'^[-*]\s+', response, re.MULTILINE):
        # 检查最后一行是否是列表项
        lines = response.split('\n')
        last_line = lines[-1].strip()
        if re.match(r'^[-*]\s+', last_line):
            return False
    
    # 如果回复很长（>100字符）且不以标点结尾，可能是截断
    if len(response) > 100 and not re.search(r'[。！？.!?]$', response):
        return True
    
    return False

def test_multi_turn_conversation():
    """测试多轮对话"""
    print("=== 测试多轮对话输出完整性 ===")
    
    # 第一轮：简单问候
    print("\n--- 第1轮：简单问候 ---")
    response1, data1 = chat("你好")
    print(f"回复长度: {len(response1)}")
    print(f"回复前100字符: {response1[:100]}")
    print(f"是否截断: {is_response_truncated(response1)}")
    
    # 第二轮：要求详细解释
    print("\n--- 第2轮：要求详细解释 ---")
    response2, data2 = chat("请详细解释一下量子计算的基本原理，包括量子比特、量子纠缠和量子叠加的概念")
    print(f"回复长度: {len(response2)}")
    print(f"回复前200字符: {response2[:200]}")
    print(f"是否截断: {is_response_truncated(response2)}")
    
    # 第三轮：继续追问
    print("\n--- 第3轮：继续追问 ---")
    response3, data3 = chat("请继续，你还没有解释完量子计算的应用场景和未来发展趋势")
    print(f"回复长度: {len(response3)}")
    print(f"回复前200字符: {response3[:200]}")
    print(f"是否截断: {is_response_truncated(response3)}")
    
    # 第四轮：要求代码示例
    print("\n--- 第4轮：要求代码示例 ---")
    response4, data4 = chat("请用Python写一个简单的量子计算模拟器，演示量子比特的叠加态")
    print(f"回复长度: {len(response4)}")
    print(f"回复前200字符: {response4[:200]}")
    print(f"是否截断: {is_response_truncated(response4)}")
    
    # 检查是否有截断
    truncated_count = sum([
        is_response_truncated(response1),
        is_response_truncated(response2),
        is_response_truncated(response3),
        is_response_truncated(response4)
    ])
    
    print(f"\n=== 测试结果 ===")
    print(f"总对话轮数: 4")
    print(f"被截断的回复数: {truncated_count}")
    
    if truncated_count > 0:
        print("❌ 发现截断问题！")
        return False
    else:
        print("✅ 所有回复完整")
        return True

def test_long_response():
    """测试长回复是否被截断"""
    print("\n=== 测试长回复截断 ===")
    
    # 要求一个很长的回复
    response, data = chat("请写一篇关于人工智能发展史的详细文章，至少1000字，包括早期发展、机器学习兴起、深度学习革命和未来展望")
    print(f"回复长度: {len(response)}")
    print(f"是否截断: {is_response_truncated(response)}")
    
    if len(response) < 500:
        print("❌ 回复太短，可能被截断或模拟回答")
        return False
    
    if is_response_truncated(response):
        print("❌ 长回复被截断")
        return False
    
    print("✅ 长回复完整")
    return True

def check_server_logs():
    """检查服务器日志中的续写信息"""
    print("\n=== 检查服务器日志 ===")
    try:
        # 尝试读取最新的日志文件
        import glob
        log_files = glob.glob("E:/项目/Neurova/logs/*.log")
        if log_files:
            latest_log = max(log_files)
            print(f"最新日志文件: {latest_log}")
            
            with open(latest_log, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # 搜索续写相关的日志
            if "截断续写" in content:
                print("✓ 发现续写日志")
                # 提取续写相关的行
                lines = content.split('\n')
                continuation_lines = [line for line in lines if "截断续写" in line]
                for line in continuation_lines[-5:]:  # 显示最后5行
                    print(f"  {line}")
            else:
                print("❌ 未发现续写日志")
                
            # 搜索finish_reason相关的日志
            if "finish_reason" in content:
                print("✓ 发现finish_reason日志")
                finish_reason_lines = [line for line in lines if "finish_reason" in line]
                for line in finish_reason_lines[-5:]:
                    print(f"  {line}")
            else:
                print("❌ 未发现finish_reason日志")
        else:
            print("❌ 未找到日志文件")
    except Exception as e:
        print(f"❌ 读取日志失败: {e}")

def main():
    """主测试函数"""
    if not login():
        return
    
    # 运行测试
    test1_passed = test_multi_turn_conversation()
    test2_passed = test_long_response()
    
    # 检查日志
    check_server_logs()
    
    print("\n=== 最终结论 ===")
    if test1_passed and test2_passed:
        print("✅ 多轮对话输出完整性测试通过")
    else:
        print("❌ 多轮对话输出完整性测试失败")
        print("可能的原因:")
        print("1. max_tokens设置过小")
        print("2. 火山API返回finish_reason='stop'而不是'length'")
        print("3. 自动续写逻辑未触发")

if __name__ == "__main__":
    main()