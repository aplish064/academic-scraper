#!/usr/bin/env python3
"""
CNKI页面结构研究工具
用于抓取和分析CNKI页面，提取特征供后续解析使用
"""

import os
import json
from datetime import datetime
from scrapling import StealthyFetcher
from bs4 import BeautifulSoup

# 输出目录
OUTPUT_DIR = "/home/hkustgz/Us/academic-scraper/temp/cnki_samples"
os.makedirs(OUTPUT_DIR, exist_ok=True)


def create_fetcher():
    """创建隐身模式的抓取器"""
    return StealthyFetcher()


def fetch_and_save_page(url: str, filename: str, fetcher) -> bool:
    """
    抓取页面并保存为HTML文件

    Args:
        url: 目标URL
        filename: 保存的文件名
        fetcher: Fetcher实例

    Returns:
        是否成功
    """
    try:
        print(f"正在抓取: {url}")
        response = fetcher.get(url)

        if response and hasattr(response, 'text'):
            html_content = response.text

            # 保存原始HTML
            filepath = os.path.join(OUTPUT_DIR, filename)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(html_content)

            print(f"✓ 已保存: {filepath}")
            return True
        else:
            print(f"❌ 抓取失败: {url}")
            return False

    except Exception as e:
        print(f"❌ 异常: {e}")
        return False


def analyze_page_structure(html_file: str):
    """
    分析页面结构，提取关键特征

    Args:
        html_file: HTML文件路径
    """
    try:
        with open(html_file, 'r', encoding='utf-8') as f:
            html_content = f.read()

        soup = BeautifulSoup(html_content, 'html.parser')

        # 提取基本信息
        title = soup.find('title')
        print(f"\n页面标题: {title.text if title else 'None'}")

        # 查找所有class和id
        all_classes = set()
        all_ids = set()

        for tag in soup.find_all(True):
            if tag.get('class'):
                all_classes.update(tag.get('class'))
            if tag.get('id'):
                all_ids.add(tag.get('id'))

        print(f"\n找到的class ({len(all_classes)} 个):")
        for cls in sorted(all_classes)[:50]:  # 只显示前50个
            print(f"  .{cls}")

        print(f"\n找到的id ({len(all_ids)} 个):")
        for tag_id in sorted(all_ids)[:50]:  # 只显示前50个
            print(f"  #{tag_id}")

        # 保存分析结果
        analysis_file = html_file.replace('.html', '_analysis.json')
        analysis_data = {
            'title': title.text if title else '',
            'classes': sorted(list(all_classes)),
            'ids': sorted(list(all_ids)),
            'meta_tags': []
        }

        # 提取meta标签
        for meta in soup.find_all('meta'):
            if meta.get('name') or meta.get('property'):
                analysis_data['meta_tags'].append({
                    'name': meta.get('name') or meta.get('property'),
                    'content': meta.get('content', '')
                })

        with open(analysis_file, 'w', encoding='utf-8') as f:
            json.dump(analysis_data, f, indent=2, ensure_ascii=False)

        print(f"\n✓ 分析结果已保存: {analysis_file}")

    except Exception as e:
        print(f"❌ 分析失败: {e}")


def main():
    """主函数"""
    print("="*80)
    print("CNKI页面结构研究工具")
    print("="*80)

    fetcher = create_fetcher()

    # CNKI测试URLs（示例，需要根据实际情况调整）
    test_urls = [
        # 期刊论文搜索页面
        {
            'url': 'https://cnki.net/kns8s/search?classid=YSTT4HG0&kw=&korder=SU',
            'filename': 'journal_search.html',
            'description': '期刊论文搜索页面'
        },
        # 学位论文搜索页面
        {
            'url': 'https://cnki.net/kns8s/search?classid=YSTY4HG0',
            'filename': 'thesis_search.html',
            'description': '学位论文搜索页面'
        },
        # 会议论文搜索页面
        {
            'url': 'https://cnki.net/kns8s/search?classid=YSU4HG0',
            'filename': 'conference_search.html',
            'description': '会议论文搜索页面'
        },
        # 专利搜索页面
        {
            'url': 'https://cnki.net/kns8s/search?classid=YSZT_HDG0',
            'filename': 'patent_search.html',
            'description': '专利搜索页面'
        },
    ]

    print(f"\n输出目录: {OUTPUT_DIR}")
    print(f"待抓取页面: {len(test_urls)} 个\n")

    # 抓取并保存页面
    success_count = 0
    for item in test_urls:
        print(f"\n[{test_urls.index(item) + 1}/{len(test_urls)}] {item['description']}")
        if fetch_and_save_page(item['url'], item['filename'], fetcher):
            success_count += 1

    print(f"\n{'='*80}")
    print(f"抓取完成: {success_count}/{len(test_urls)}")

    # 分析所有保存的HTML文件
    print(f"\n开始分析页面结构...")
    for item in test_urls:
        filepath = os.path.join(OUTPUT_DIR, item['filename'])
        if os.path.exists(filepath):
            print(f"\n分析: {item['description']}")
            analyze_page_structure(filepath)

    print(f"\n{'='*80}")
    print("研究完成！请查看以下目录:")
    print(f"  HTML文件: {OUTPUT_DIR}/")
    print(f"  分析结果: {OUTPUT_DIR}/*_analysis.json")


if __name__ == "__main__":
    main()
