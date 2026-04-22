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

# 数据表配置
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