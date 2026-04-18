#!/usr/bin/env python3
"""
测试dashboard缓存机制
"""

import requests
import time

BASE_URL = "http://localhost:8080"

def test_cache_mechanism():
    """测试缓存机制"""
    print("="*60)
    print("测试Dashboard缓存机制")
    print("="*60)

    # 测试各个数据源
    sources = ['openalex', 'semantic', 'all']

    for source in sources:
        print(f"\n{'='*60}")
        print(f"测试数据源: {source}")
        print(f"{'='*60}")

        # 第一次请求（应该从数据库查询）
        print("第1次请求（预期：从数据库查询）...")
        start_time = time.time()
        try:
            response = requests.get(f"{BASE_URL}/api/aggregated?source={source}")
            elapsed_time = time.time() - start_time

            if response.status_code == 200:
                data = response.json()
                print(f"  ✅ 成功 | 耗时: {elapsed_time:.2f}秒 | 论文数: {data.get('statistics', {}).get('total_papers', 0):,}")
            else:
                print(f"  ❌ 失败 | 状态码: {response.status_code}")
        except Exception as e:
            print(f"  ❌ 异常: {e}")

        # 第二次请求（应该从缓存读取）
        print("第2次请求（预期：从缓存读取）...")
        start_time = time.time()
        try:
            response = requests.get(f"{BASE_URL}/api/aggregated?source={source}")
            elapsed_time = time.time() - start_time

            if response.status_code == 200:
                data = response.json()
                print(f"  ✅ 成功 | 耗时: {elapsed_time:.2f}秒 | 论文数: {data.get('statistics', {}).get('total_papers', 0):,}")

                # 如果耗时很短（< 1秒），说明命中缓存
                if elapsed_time < 1.0:
                    print(f"  🎯 命中缓存！")
            else:
                print(f"  ❌ 失败 | 状态码: {response.status_code}")
        except Exception as e:
            print(f"  ❌ 异常: {e}")

    print(f"\n{'='*60}")
    print("测试完成")
    print(f"{'='*60}")
    print("\n💡 提示：")
    print("  - 如果第2次请求耗时 < 1秒，说明缓存工作正常")
    print("  - 缓存将每2分钟自动刷新")
    print("  - 服务器日志会显示刷新进度")


if __name__ == '__main__':
    try:
        test_cache_mechanism()
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断")
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
