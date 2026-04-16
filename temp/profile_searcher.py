#!/usr/bin/env python3
"""
个人主页搜索器 - 支持多种搜索引擎
"""

import asyncio
import aiohttp
from typing import Dict, List, Any, Optional
from enum import Enum


class SearchEngine(Enum):
    DUCKDUCKGO = "duckduckgo"
    SERPAPI = "serpapi"


class ProfileSearcher:
    def __init__(self, engine: SearchEngine = SearchEngine.DUCKDUCKGO, serpapi_key: str = None):
        """
        初始化搜索器

        Args:
            engine: 搜索引擎类型
            serpapi_key: SerpAPI key（如果使用 SerpAPI）
        """
        self.engine = engine
        self.serpapi_key = serpapi_key

        if engine == SearchEngine.SERPAPI and not serpapi_key:
            raise ValueError("使用 SerpAPI 必须提供 serpapi_key")

    async def search_author_profile(self, author_info: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        搜索作者个人主页

        Args:
            author_info: 作者信息字典

        Returns:
            List of search results with url, title, snippet
        """
        # 生成搜索查询
        queries = self._generate_search_queries(author_info)

        # 执行搜索
        all_results = []
        for query in queries:
            try:
                if self.engine == SearchEngine.DUCKDUCKGO:
                    results = await self._search_duckduckgo(query)
                elif self.engine == SearchEngine.SERPAPI:
                    results = await self._search_serpapi(query)
                else:
                    raise ValueError(f"不支持的搜索引擎: {self.engine}")

                all_results.extend(results)
            except Exception as e:
                print(f"   ⚠️  搜索失败 '{query}': {e}")
                continue

        # 去重
        seen_urls = set()
        unique_results = []
        for result in all_results:
            if result['url'] not in seen_urls:
                seen_urls.add(result['url'])
                unique_results.append(result)

        return unique_results

    def _generate_search_queries(self, author_info: Dict[str, Any]) -> List[str]:
        """
        生成搜索查询

        策略：
        1. 作者名 + ORCID
        2. 作者名 + Google Scholar
        3. 作者名 + 最新机构
        4. 作者名 + 研究领域
        5. 作者名 + GitHub
        6. 作者中文名 + 机构
        """
        name = author_info['author_name']
        institution = author_info.get('latest_institution', '')
        research_fields = author_info.get('research_fields', [])

        queries = []

        # 英文查询
        queries.append(f"{name} ORCID")
        queries.append(f"{name} Google Scholar")
        queries.append(f"{name} GitHub")

        if institution:
            queries.append(f'"{name}" "{institution}"')
            queries.append(f"{name} {institution} researcher")

        if research_fields:
            top_field = research_fields[0]
            queries.append(f"{name} {top_field}")

        # 如果是中文名，添加中文查询
        if self._contains_chinese(name):
            if institution:
                # 尝试提取机构的英文名
                queries.append(f"{name} {institution}")
                queries.append(f"{name} 个人主页")

        return queries[:8]  # 限制查询数量

    def _contains_chinese(self, text: str) -> bool:
        """检查是否包含中文"""
        return any('\u4e00' <= char <= '\u9fff' for char in text)

    async def _search_duckduckgo(self, query: str) -> List[Dict[str, Any]]:
        """使用 DuckDuckGo 搜索"""
        try:
            from duckduckgo_search import DDGS
            ddgs = DDGS()

            results = []
            search_results = ddgs.text(query, max_results=10)

            for result in search_results:
                results.append({
                    'url': result.get('link', ''),
                    'title': result.get('title', ''),
                    'snippet': result.get('body', ''),
                    'source': 'duckduckgo'
                })

            return results

        except ImportError:
            print("   ❌ 请安装 duckduckgo-search: pip install duckduckgo-search")
            return []
        except Exception as e:
            print(f"   ⚠️  DuckDuckGo 搜索出错: {e}")
            return []

    async def _search_serpapi(self, query: str) -> List[Dict[str, Any]]:
        """使用 SerpAPI 搜索"""
        try:
            import requests

            url = "https://serpapi.com/search.json"
            params = {
                "engine": "google",
                "q": query,
                "api_key": self.serpapi_key,
                "num": 10
            }

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()
            results = []

            # 解析 organic results
            for result in data.get('organic_results', []):
                results.append({
                    'url': result.get('link', ''),
                    'title': result.get('title', ''),
                    'snippet': result.get('snippet', ''),
                    'source': 'serpapi'
                })

            # 解析 knowledge graph（如果有）
            if 'knowledge_graph' in data:
                kg = data['knowledge_graph']
                if 'source' in kg:
                    results.append({
                        'url': kg['source'].get('link', ''),
                        'title': kg.get('title', ''),
                        'snippet': kg.get('description', ''),
                        'source': 'serpapi_kg'
                    })

            return results

        except ImportError:
            print("   ❌ 请安装 requests: pip install requests")
            return []
        except Exception as e:
            print(f"   ⚠️  SerpAPI 搜索出错: {e}")
            return []

    async def fetch_page_content(self, url: str, timeout: int = 10) -> Optional[str]:
        """
        获取页面内容

        Args:
            url: 页面 URL
            timeout: 超时时间（秒）

        Returns:
            页面文本内容
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=timeout) as response:
                    if response.status == 200:
                        # 尝试解码
                        content = await response.text()

                        # 简单提取文本（去除 HTML 标签）
                        from bs4 import BeautifulSoup
                        soup = BeautifulSoup(content, 'html.parser')

                        # 移除脚本和样式
                        for script in soup(['script', 'style']):
                            script.decompose()

                        text = soup.get_text(separator='\n', strip=True)

                        # 限制长度
                        if len(text) > 10000:
                            text = text[:10000]

                        return text
                    else:
                        return None

        except ImportError:
            print("   ❌ 请安装 beautifulsoup4: pip install beautifulsoup4")
            return None
        except Exception as e:
            print(f"   ⚠️  获取页面内容失败 {url}: {e}")
            return None


async def main():
    """测试函数"""
    print("=" * 80)
    print("个人主页搜索器测试")
    print("=" * 80)
    print()

    # 测试数据
    test_author = {
        'author_name': 'Yann LeCun',
        'latest_institution': 'New York University',
        'research_fields': ['Machine Learning', 'Computer Vision'],
        'papers': [
            {'title': 'Deep learning', 'year': 2015},
        ]
    }

    print(f"🔍 搜索作者: {test_author['author_name']}")
    print()

    # 测试 DuckDuckGo
    print("使用 DuckDuckGo 搜索...")
    searcher_ddg = ProfileSearcher(engine=SearchEngine.DUCKDUCKGO)
    results_ddg = await searcher_ddg.search_author_profile(test_author)

    print(f"   找到 {len(results_ddg)} 个结果:")
    for i, result in enumerate(results_ddg[:5], 1):
        print(f"   {i}. {result['title']}")
        print(f"      URL: {result['url'][:80]}")
        print()

    print()
    print("=" * 80)


if __name__ == '__main__':
    asyncio.run(main())
