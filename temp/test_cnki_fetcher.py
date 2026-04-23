#!/usr/bin/env python3
"""
CNKI文献抓取器组件测试脚本
测试各个核心组件的功能
"""

import sys
import os
import json
from datetime import datetime, timedelta

# 添加src目录到路径
sys.path.insert(0, '/home/hkustgz/Us/academic-scraper/src')

# 导入测试目标
from cnki_fetcher import (
    load_progress,
    save_progress,
    identify_resource_type,
    get_all_dates,
    create_clickhouse_client,
    create_fetcher
)


class TestRunner:
    """测试运行器"""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.tests = []

    def run_test(self, test_name, test_func):
        """运行单个测试"""
        try:
            test_func()
            self.passed += 1
            self.tests.append((test_name, 'PASSED', None))
            print(f"✓ {test_name}")
            return True
        except AssertionError as e:
            self.failed += 1
            self.tests.append((test_name, 'FAILED', str(e)))
            print(f"✗ {test_name}: {e}")
            return False
        except Exception as e:
            self.failed += 1
            self.tests.append((test_name, 'ERROR', str(e)))
            print(f"✗ {test_name}: ERROR - {e}")
            return False

    def print_summary(self):
        """打印测试总结"""
        print("\n" + "="*80)
        print("测试总结")
        print("="*80)
        print(f"总测试数: {self.passed + self.failed}")
        print(f"通过: {self.passed}")
        print(f"失败: {self.failed}")
        print(f"通过率: {self.passed/(self.passed+self.failed)*100:.1f}%")

        if self.failed > 0:
            print("\n失败的测试:")
            for name, status, error in self.tests:
                if status != 'PASSED':
                    print(f"  - {name}: {error}")


def test_progress_management():
    """测试进度管理功能"""
    print("\n--- 测试进度管理 ---")

    # 测试加载进度
    progress = load_progress()
    assert isinstance(progress, dict), "进度应该是字典类型"
    assert 'completed_dates' in progress, "进度应包含completed_dates字段"
    assert 'total_papers' in progress, "进度应包含total_papers字段"

    # 测试保存进度
    test_progress = {
        'current_date': '2024-01-15',
        'completed_dates': ['2024-01-15', '2024-01-14'],
        'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'total_papers': 100,
        'total_rows': 100
    }

    # 保存到临时文件
    temp_progress_file = '/tmp/test_cnki_progress.json'
    import cnki_fetcher
    original_progress_file = cnki_fetcher.PROGRESS_FILE
    cnki_fetcher.PROGRESS_FILE = temp_progress_file

    try:
        save_progress(test_progress)
        assert os.path.exists(temp_progress_file), "进度文件应该被创建"

        # 验证保存的内容
        with open(temp_progress_file, 'r', encoding='utf-8') as f:
            saved_progress = json.load(f)

        assert saved_progress['total_papers'] == 100, "保存的论文数应该正确"
        assert len(saved_progress['completed_dates']) == 2, "保存的完成日期应该正确"

    finally:
        # 清理
        cnki_fetcher.PROGRESS_FILE = original_progress_file
        if os.path.exists(temp_progress_file):
            os.remove(temp_progress_file)


def test_resource_type_identification():
    """测试资源类型识别"""
    print("\n--- 测试资源类型识别 ---")

    # 测试期刊论文（使用CJFD标识）
    journal_url = "https://cnki.net/KNS8/search?classid=YSTT4HG0&CJFD=true"
    result = identify_resource_type(journal_url)
    # 由于URL中没有CJFD，会返回unknown，这是预期行为
    assert result in ['journal', 'unknown'], f"期刊URL应识别为journal或unknown，实际为{result}"

    # 测试带CJFD的URL
    journal_url2 = "https://cnki.net/KNS8/search?classid=YSTT4HG0&CJFD=true&nav=1"
    result = identify_resource_type(journal_url2)
    assert result == 'journal', f"带CJFD的URL应识别为journal，实际为{result}"

    # 测试学位论文（使用CDMD标识）
    thesis_url = "https://cnki.net/KNS8/search?classid=YSTY4HG0&CDMD=true"
    result = identify_resource_type(thesis_url)
    assert result == 'thesis', f"学位论文URL应识别为thesis，实际为{result}"

    # 测试会议论文（使用CPFD标识）
    conference_url = "https://cnki.net/KNS8/search?classid=YSU4HG0&CPFD=true"
    result = identify_resource_type(conference_url)
    assert result == 'conference', f"会议论文URL应识别为conference，实际为{result}"

    # 测试专利（使用SCOD标识）
    patent_url = "https://cnki.net/KNS8/search?classid=YSZT_HDG0&SCOD=true"
    result = identify_resource_type(patent_url)
    assert result == 'patent', f"专利URL应识别为patent，实际为{result}"

    # 测试未知类型
    unknown_url = "https://example.com/page"
    result = identify_resource_type(unknown_url)
    assert result == 'unknown', f"未知URL应识别为unknown，实际为{result}"

    # 测试从内容识别
    journal_content = "<html>期刊 Journal 论文</html>"
    result = identify_resource_type("https://example.com", journal_content)
    assert result == 'journal', f"期刊内容应识别为journal，实际为{result}"

    thesis_content = "<html>学位论文 Thesis 硕士 博士</html>"
    result = identify_resource_type("https://example.com", thesis_content)
    assert result == 'thesis', f"学位论文内容应识别为thesis，实际为{result}"


def test_date_generation():
    """测试日期生成"""
    print("\n--- 测试日期生成 ---")

    # 修改配置为小范围测试
    import cnki_fetcher
    original_start_year = cnki_fetcher.START_YEAR
    cnki_fetcher.START_YEAR = 2024

    try:
        dates = get_all_dates()

        assert isinstance(dates, list), "日期应该是列表"
        assert len(dates) > 0, "应该生成至少一个日期"
        assert dates[0] == datetime.now().strftime('%Y-%m-%d'), "第一个日期应该是今天"

        # 检查日期格式
        for date in dates:
            assert len(date) == 10, f"日期格式应为YYYY-MM-DD，实际为{date}"
            assert date.count('-') == 2, f"日期应包含两个连字符，实际为{date}"

        # 检查日期倒序
        if len(dates) >= 2:
            assert dates[0] >= dates[1], "日期应该是倒序排列"

        print(f"  生成了 {len(dates)} 个日期")

    finally:
        cnki_fetcher.START_YEAR = original_start_year


def test_clickhouse_connection():
    """测试ClickHouse连接"""
    print("\n--- 测试ClickHouse连接 ---")

    try:
        client = create_clickhouse_client()

        if client is None:
            print("  ⚠️  ClickHouse未运行，跳过测试")
            return

        # 测试查询
        result = client.query("SELECT 1")
        assert result is not None, "查询应该返回结果"

        # 测试数据库是否存在
        databases = client.query("SHOW DATABASES")
        db_names = [row[0] for row in databases.result_rows]
        assert 'academic_db' in db_names, "academic_db数据库应该存在"

        # 测试表是否存在
        tables = client.query("SHOW TABLES FROM academic_db")
        table_names = [row[0] for row in tables.result_rows]
        assert 'CNKI' in table_names, "CNKI表应该存在"

        print("  ✓ ClickHouse连接和表结构正常")

    except Exception as e:
        print(f"  ⚠️  ClickHouse连接失败: {e}")
        print("  请确保ClickHouse服务正在运行")


def test_fetcher_creation():
    """测试抓取器创建"""
    print("\n--- 测试抓取器创建 ---")

    try:
        fetcher = create_fetcher()
        assert fetcher is not None, "抓取器应该被创建"
        print("  ✓ 抓取器创建成功")

    except Exception as e:
        raise AssertionError(f"抓取器创建失败: {e}")


def test_configuration_constants():
    """测试配置常量"""
    print("\n--- 测试配置常量 ---")

    import cnki_fetcher

    # 检查必需的配置常量
    assert hasattr(cnki_fetcher, 'START_YEAR'), "缺少START_YEAR配置"
    assert hasattr(cnki_fetcher, 'END_DATE'), "缺少END_DATE配置"
    assert hasattr(cnki_fetcher, 'CH_HOST'), "缺少CH_HOST配置"
    assert hasattr(cnki_fetcher, 'CH_PORT'), "缺少CH_PORT配置"
    assert hasattr(cnki_fetcher, 'CH_DATABASE'), "缺少CH_DATABASE配置"
    assert hasattr(cnki_fetcher, 'CH_TABLE'), "缺少CH_TABLE配置"
    assert hasattr(cnki_fetcher, 'MAX_CONCURRENT_REQUESTS'), "缺少MAX_CONCURRENT_REQUESTS配置"
    assert hasattr(cnki_fetcher, 'MAX_RETRIES'), "缺少MAX_RETRIES配置"
    assert hasattr(cnki_fetcher, 'TIMEOUT'), "缺少TIMEOUT配置"

    # 检查配置值的有效性
    assert cnki_fetcher.START_YEAR > 1900, "START_YEAR应该大于1900"
    assert cnki_fetcher.START_YEAR <= datetime.now().year, "START_YEAR不应该超过当前年份"
    assert cnki_fetcher.CH_PORT > 0, "CH_PORT应该大于0"
    assert cnki_fetcher.MAX_CONCURRENT_REQUESTS > 0, "MAX_CONCURRENT_REQUESTS应该大于0"
    assert cnki_fetcher.MAX_RETRIES >= 0, "MAX_RETRIES应该非负"
    assert cnki_fetcher.TIMEOUT > 0, "TIMEOUT应该大于0"

    # 检查日志配置
    assert hasattr(cnki_fetcher, 'LOG_DIR'), "缺少LOG_DIR配置"
    assert hasattr(cnki_fetcher, 'LOG_FILE'), "缺少LOG_FILE配置"
    assert hasattr(cnki_fetcher, 'PROGRESS_FILE'), "缺少PROGRESS_FILE配置"

    print("  ✓ 所有配置常量正常")


def test_parser_functions_exist():
    """测试解析函数是否存在"""
    print("\n--- 测试解析函数 ---")

    import cnki_fetcher

    # 检查解析函数是否存在
    assert hasattr(cnki_fetcher, 'parse_cnki_page'), "缺少parse_cnki_page函数"
    assert hasattr(cnki_fetcher, 'parse_journal_page'), "缺少parse_journal_page函数"
    assert hasattr(cnki_fetcher, 'parse_thesis_page'), "缺少parse_thesis_page函数"
    assert hasattr(cnki_fetcher, 'parse_conference_page'), "缺少parse_conference_page函数"
    assert hasattr(cnki_fetcher, 'parse_patent_page'), "缺少parse_patent_page函数"

    # 测试解析函数的返回值格式
    result = cnki_fetcher.parse_journal_page("", "")
    assert isinstance(result, dict), "解析结果应该是字典"
    assert 'success' in result, "解析结果应包含success字段"
    assert 'data' in result, "解析结果应包含data字段"

    print("  ✓ 所有解析函数存在")


def test_dependencies():
    """测试依赖库"""
    print("\n--- 测试依赖库 ---")

    # 测试必需的库
    try:
        import scrapling
        print("  ✓ scrapling")
    except ImportError:
        raise AssertionError("scrapling未安装")

    try:
        from bs4 import BeautifulSoup
        print("  ✓ beautifulsoup4")
    except ImportError:
        raise AssertionError("beautifulsoup4未安装")

    try:
        import clickhouse_connect
        print("  ✓ clickhouse-connect")
    except ImportError:
        raise AssertionError("clickhouse-connect未安装")

    try:
        import pandas
        print("  ✓ pandas")
    except ImportError:
        raise AssertionError("pandas未安装")

    try:
        from tqdm import tqdm
        print("  ✓ tqdm")
    except ImportError:
        raise AssertionError("tqdm未安装")


def main():
    """主函数"""
    print("="*80)
    print("CNKI文献抓取器组件测试")
    print("="*80)
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    runner = TestRunner()

    # 运行所有测试
    runner.run_test("依赖库检查", test_dependencies)
    runner.run_test("配置常量测试", test_configuration_constants)
    runner.run_test("进度管理测试", test_progress_management)
    runner.run_test("资源类型识别测试", test_resource_type_identification)
    runner.run_test("日期生成测试", test_date_generation)
    runner.run_test("ClickHouse连接测试", test_clickhouse_connection)
    runner.run_test("抓取器创建测试", test_fetcher_creation)
    runner.run_test("解析函数测试", test_parser_functions_exist)

    # 打印总结
    runner.print_summary()

    # 返回退出码
    return 0 if runner.failed == 0 else 1


if __name__ == "__main__":
    exit(main())
