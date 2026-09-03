#!/usr/bin/env python3
"""临时脚本：运行所有重构导入测试"""
import sys
import traceback

try:
    # 导入测试模块
    from tests.unit.test_refactor_imports import (
        TestContextImports,
        TestCollaborateImports, 
        TestWorkflowImports,
        TestEndToEndFunctionality
    )
    
    # 运行所有测试类
    test_classes = [
        TestContextImports,
        TestCollaborateImports,
        TestWorkflowImports,
        TestEndToEndFunctionality
    ]
    
    total_tests = 0
    passed_tests = 0
    failed_tests = 0
    
    for test_class in test_classes:
        print(f"\n{'='*60}")
        print(f"运行测试类: {test_class.__name__}")
        print('='*60)
        
        test_instance = test_class()
        
        # 获取所有测试方法
        test_methods = [method for method in dir(test_instance) if method.startswith('test_')]
        
        for method_name in test_methods:
            total_tests += 1
            print(f"\n运行测试: {method_name}")
            
            try:
                method = getattr(test_instance, method_name)
                method()
                print(f"✓ {method_name} 通过")
                passed_tests += 1
            except Exception as e:
                print(f"✗ {method_name} 失败:")
                traceback.print_exc()
                failed_tests += 1
    
    print(f"\n{'='*60}")
    print(f"测试结果汇总:")
    print(f"总测试数: {total_tests}")
    print(f"通过: {passed_tests}")
    print(f"失败: {failed_tests}")
    print('='*60)
    
    if failed_tests > 0:
        sys.exit(1)
        
except Exception as e:
    print("导入测试模块失败:")
    traceback.print_exc()
    sys.exit(1)