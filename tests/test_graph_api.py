"""作者合作关系图谱API单元测试

这些测试验证作者合作关系图谱API端点的功能。
测试需要ClickHouse数据库运行。

运行测试:
    python -m pytest tests/test_graph_api.py -v

注意: 部分测试可能因数据库连接或SQL问题失败
"""

import unittest
import sys
import os

# 添加dashboard目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'dashboard'))

from api_server import app
import json


class TestGraphAPI(unittest.TestCase):
    """图谱API测试类"""

    def setUp(self):
        """每个测试前的设置"""
        self.app = app
        self.client = self.app.test_client()

    def test_get_authors_basic(self):
        """测试基础作者查询"""
        response = self.client.get('/api/graph/authors')
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.data)
        self.assertIn('nodes', data)
        self.assertIn('total_authors', data)
        self.assertIn('filtered_authors', data)
        self.assertLessEqual(len(data['nodes']), 200)  # 默认max_nodes=200

    def test_get_authors_with_filters(self):
        """测试带筛选条件的作者查询"""
        response = self.client.get('/api/graph/authors?min_collaborations=5&max_nodes=100&time_range=2')
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.data)
        self.assertIn('nodes', data)
        self.assertLessEqual(len(data['nodes']), 100)

        # 验证所有节点的合作次数都>=5
        for node in data['nodes']:
            self.assertGreaterEqual(node['degree'], 5)

    def test_get_authors_invalid_params(self):
        """测试无效参数"""
        # max_nodes超过500
        response = self.client.get('/api/graph/authors?max_nodes=1000')
        self.assertEqual(response.status_code, 400)

        data = json.loads(response.data)
        self.assertTrue(data.get('error'))
        self.assertIn('message', data)
        self.assertIn('code', data)

    def test_get_edges_basic(self):
        """测试基础合作关系查询"""
        # 先获取一些作者ID
        authors_response = self.client.get('/api/graph/authors?max_nodes=10')
        authors_data = json.loads(authors_response.data)

        self.assertIn('nodes', authors_data, "Authors API should return 'nodes' key")
        if not authors_data['nodes']:
            self.skipTest("No author nodes available for testing edges")
        author_ids = [node['id'] for node in authors_data['nodes'][:5]]

        # 查询这些作者的合作关系
        response = self.client.get('/api/graph/edges', query_string={
            'author_ids': author_ids,
            'min_weight': 1
        })
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.data)
        self.assertIn('edges', data)
        self.assertIn('total_collaborations', data)

    def test_get_edges_missing_params(self):
        """测试缺少必需参数"""
        response = self.client.get('/api/graph/edges')
        self.assertEqual(response.status_code, 400)

        data = json.loads(response.data)
        self.assertTrue(data.get('error'))
        self.assertIn('message', data)
        self.assertIn('code', data)

    def test_get_stats(self):
        """测试统计数据查询"""
        response = self.client.get('/api/graph/stats')
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.data)
        self.assertIn('total_papers', data)
        self.assertIn('total_authors', data)
        self.assertIn('total_collaborations', data)
        self.assertIn('avg_collaboration_degree', data)
        self.assertIn('max_collaboration_degree', data)

        # 验证数据类型
        self.assertIsInstance(data['total_papers'], int)
        self.assertIsInstance(data['total_authors'], int)


if __name__ == '__main__':
    unittest.main()
