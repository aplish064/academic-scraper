"""
数据源适配器基类
定义所有数据源必须实现的接口
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional


class DataSourceAdapter(ABC):
    """
    数据源适配器抽象基类
    每个数据源需要实现这些方法以支持统一的数据访问接口
    """

    def __init__(self, source_name: str, config: Dict[str, Any]):
        """
        初始化适配器

        Args:
            source_name: 数据源名称（如 'openalex', 'dblp'）
            config: 数据源配置字典
        """
        self.source_name = source_name
        self.config = config
        self.table = config.get('table', '')
        self.fields = config.get('fields', {})
        self.supports = config.get('supports', {})

    def get_table(self) -> str:
        """获取表名"""
        return self.table

    def get_field(self, field_name: str) -> Optional[str]:
        """
        获取字段映射

        Args:
            field_name: 逻辑字段名（如 'date', 'author', 'journal'）

        Returns:
            实际字段名，如果字段不存在返回 None
        """
        return self.fields.get(field_name)

    def supports_metric(self, metric: str) -> bool:
        """
        检查是否支持某个指标

        Args:
            metric: 指标名称（如 'citations', 'fwci'）

        Returns:
            是否支持该指标
        """
        return self.supports.get(metric, False)

    @abstractmethod
    def get_statistics_sql(self) -> str:
        """
        获取统计查询SQL

        Returns:
            SQL查询字符串，应返回: total_papers, unique_authors, unique_journals,
                                  unique_institutions, high_citations, avg_fwci
        """
        pass

    @abstractmethod
    def get_date_field(self) -> str:
        """获取日期字段名"""
        pass

    @abstractmethod
    def get_journal_field(self) -> str:
        """获取期刊/会议字段名"""
        pass

    @abstractmethod
    def get_author_field(self) -> str:
        """获取作者字段名"""
        pass

    @abstractmethod
    def get_venue_field(self) -> str:
        """获取发表场所字段名（venue）"""
        pass

    @abstractmethod
    def get_doi_field(self) -> str:
        """获取DOI字段名"""
        pass

    def get_date_format(self) -> str:
        """
        获取日期格式类型

        Returns:
            'publication_date' 或 'year'
        """
        return self.config.get('date_format', 'publication_date')

    def get_supported_metrics(self) -> List[str]:
        """
        获取支持的指标列表

        Returns:
            支持的指标名称列表
        """
        return [k for k, v in self.supports.items() if v]

    def format_date_query(self, field: str = None) -> str:
        """
        格式化日期查询字段

        Args:
            field: 日期字段名，如果为None则使用get_date_field()

        Returns:
            格式化的SQL日期表达式
        """
        date_field = field or self.get_date_field()

        if self.get_date_format() == 'year':
            # DBLP 使用年份格式
            return f"concat({date_field}, '-01')"
        else:
            # 其他使用完整日期格式
            return f"formatDateTime(toDateOrNull({date_field}), '%Y-%m')"

    def validate_result(self, result) -> bool:
        """
        验证查询结果是否有效

        Args:
            result: ClickHouse查询结果对象

        Returns:
            结果是否有效
        """
        return result is not None and hasattr(result, 'result_rows') and result.result_rows
