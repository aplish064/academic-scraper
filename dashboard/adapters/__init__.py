"""
数据源适配器模块
支持动态添加新数据源而无需修改核心代码
"""
from .base import DataSourceAdapter
from .openalex import OpenAlexAdapter
from .dblp import DBLPAdapter
from .semantic import SemanticAdapter
from .arxiv import ArXivAdapter

# 注册所有适配器
ADAPTERS = {
    'openalex': OpenAlexAdapter(),
    'dblp': DBLPAdapter(),
    'semantic': SemanticAdapter(),
    'arxiv': ArXivAdapter()
}

def get_adapter(source: str) -> DataSourceAdapter:
    """获取数据源适配器"""
    return ADAPTERS.get(source)

def register_adapter(source: str, adapter: DataSourceAdapter):
    """注册新适配器 - 用于动态添加数据源"""
    ADAPTERS[source] = adapter

__all__ = ['DataSourceAdapter', 'get_adapter', 'register_adapter', 'ADAPTERS']
