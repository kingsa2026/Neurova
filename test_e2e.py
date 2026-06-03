#!/usr/bin/env python3
"""临时脚本：运行端到端功能测试"""
import sys
import traceback

try:
    # 导入测试模块
    from tests.test_refactor_imports import TestEndToEndFunctionality
    
    # 创建测试实例
    test_instance = TestEndToEndFunctionality()
    
    # 运行所有测试方法
    test_methods = [
        'test_context_builder_instantiation',
        'test_token_budget_defaults', 
        'test_template_type_enum_values',
        'test_flow_phase_enum_values'
    ]
    
    for method_name in test_methods:
        print(f"\n{'='*60}")
        print(f"运行测试: {method_name}")
        print('='*60)
        
        try:
            method = getattr(test_instance, method_name)
            method()
            print(f"✓ {method_name} 通过")
        except Exception as e:
            print(f"✗ {method_name} 失败:")
            traceback.print_exc()
            
except Exception as e:
    print("导入测试模块失败:")
    traceback.print_exc()
    sys.exit(1)