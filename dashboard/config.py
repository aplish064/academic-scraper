"""
学术数据看板配置文件
"""

# ClickHouse数据库配置
CLICKHOUSE_CONFIG = {
    'host': 'localhost',
    'port': 8123,
    'database': 'academic_db',
    'username': 'default',
    'password': ''
}

# Redis缓存配置
REDIS_CONFIG = {
    'host': 'localhost',
    'port': 6379,
    'db': 0,
    'decode_responses': True
}

# 数据表配置（保持向后兼容）
TABLES = {
    'openalex': 'OpenAlex',       # OpenAlex数据表
    'semantic': 'semantic',        # Semantic Scholar数据表
    'dblp': 'dblp',                # DBLP数据表
    'arxiv': 'arxiv'              # arXiv数据表
}

# 默认数据表
DEFAULT_TABLE = 'openalex'

# Flask服务配置
FLASK_CONFIG = {
    'host': '0.0.0.0',
    'port': 8080,
    'debug': False
}

# 数据查询配置
QUERY_CONFIG = {
    'default_limit': 1000,        # 默认查询限制
    'max_limit': 10000,           # 最大查询限制
    'cache_ttl': 600,             # 缓存时间（秒）
    'recent_days': 30             # 最近天数
}

# 数据源详细配置 - 用于支持新数据源的添加
DATA_SOURCES = {
    'openalex': {
        'table': 'OpenAlex',
        'enabled': True,
        'priority': 1,
        'fields': {
            'date': 'publication_date',
            'journal': 'journal',
            'venue': 'journal',  # 统一使用venue字段
            'author': 'author_id',
            'author_name': 'author_id',  # 用于统一作者字段
            'doi': 'doi',
            'institution': 'institution_name',
            'country': 'institution_country',
            'citation_count': 'citation_count',
            'fwci': 'fwci',
            'tag': 'tag',
            'institution_type': 'institution_type'
        },
        'supports': {
            'citations': True,
            'fwci': True,
            'institutions': True,
            'countries': True,
            'institution_types': True,
            'ccf_class': False,
            'pub_type': False,
            'venue_type': False,
            'categories': False
        },
        'date_format': 'publication_date',
        'ui': {
            'name': 'OpenAlex',
            'shows_charts': ['country', 'institution', 'fwci', 'citation', 'papers_trend', 'journal'],
            'shows_stats': ['institutions', 'fwci', 'high_citations']
        }
    },
    'dblp': {
        'table': 'dblp',
        'enabled': True,
        'priority': 2,
        'fields': {
            'date': 'year',
            'journal': 'venue',
            'venue': 'venue',
            'author': 'author_name',
            'author_name': 'author_name',
            'doi': 'doi',
            'institution': 'institution',
            'country': None,
            'citation_count': None,
            'fwci': None,
            'tag': None,
            'institution_type': None,
            'ccf_class': 'ccf_class',
            'pub_type': 'publtype',
            'venue_type': 'venue_type'
        },
        'supports': {
            'citations': False,
            'fwci': False,
            'institutions': False,
            'countries': False,
            'institution_types': False,
            'ccf_class': True,
            'pub_type': True,
            'venue_type': True,
            'categories': False
        },
        'date_format': 'year',
        'ui': {
            'name': 'DBLP',
            'shows_charts': ['ccf_class', 'pub_type', 'venue_type', 'papers_trend', 'journal'],
            'shows_stats': []
        }
    },
    'semantic': {
        'table': 'semantic',
        'enabled': True,
        'priority': 3,
        'fields': {
            'date': 'publication_date',
            'journal': 'journal',
            'venue': 'venue',
            'author': 'author_id',
            'author_name': 'author_id',
            'doi': 'doi',
            'institution': 'institution_name',
            'country': 'institution_country',
            'citation_count': 'citation_count',
            'fwci': None,
            'tag': 'tag',
            'institution_type': 'institution_type'
        },
        'supports': {
            'citations': True,
            'fwci': False,
            'institutions': False,
            'countries': False,
            'institution_types': False,
            'ccf_class': False,
            'pub_type': False,
            'venue_type': False,
            'categories': False
        },
        'date_format': 'publication_date',
        'ui': {
            'name': 'Semantic Scholar',
            'shows_charts': ['citation', 'papers_trend', 'journal'],
            'shows_stats': ['high_citations']
        }
    },
    'arxiv': {
        'table': 'arxiv',
        'enabled': True,
        'priority': 4,
        'fields': {
            'date': 'published',
            'journal': 'journal_ref',
            'venue': 'journal_ref',
            'author': 'author',
            'author_name': 'author',
            'doi': None,
            'institution': None,
            'country': None,
            'citation_count': None,
            'fwci': None,
            'tag': None,
            'institution_type': None,
            'primary_category': 'primary_category'
        },
        'supports': {
            'citations': False,
            'fwci': False,
            'institutions': False,
            'countries': False,
            'institution_types': False,
            'ccf_class': False,
            'pub_type': False,
            'venue_type': False,
            'categories': True
        },
        'date_format': 'published',
        'ui': {
            'name': 'arXiv',
            'shows_charts': ['category', 'timeline'],
            'shows_stats': ['unique_categories', 'time_range']
        }
    }
}

# 辅助函数
def get_enabled_sources():
    """获取所有启用的数据源"""
    return [k for k, v in DATA_SOURCES.items() if v['enabled']]

def get_source_config(source: str):
    """获取数据源配置"""
    return DATA_SOURCES.get(source, {})

def get_field_mapping(source: str, field: str):
    """获取字段映射"""
    config = get_source_config(source)
    return config.get('fields', {}).get(field)

def get_table_name(source: str):
    """获取数据源对应的表名"""
    config = get_source_config(source)
    return config.get('table', TABLES.get(source, source))