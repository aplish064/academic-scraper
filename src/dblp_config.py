# src/dblp_config.py
"""DBLP Fetcher 配置"""

# DBLP 数据源
DBLP_DROPS_BASE = "https://drops.dagstuhl.de/entities/artifact/10.4230"
DBLP_XML_MIRROR = "https://dblp.uni-trier.de/xml"
DBLP_AUTHOR_API = "https://dblp.org/search/author/api"
DBLP_PERSON_API = "https://dblp.org/pid"

# 并发配置
XML_PARSER_THREADS = 50              # XML解析线程数
AUTHOR_API_CONCURRENT = 100          # 作者API并发数
CH_BATCH_SIZE = 9000                  # ClickHouse批量大小

# 超时配置
REQUEST_TIMEOUT = 20                  # API请求超时（秒）
MAX_RETRIES = 3                       # 最大重试次数

# 文件路径
DATA_DIR = "/home/hkustgz/Us/academic-scraper/data"
LOG_DIR = "/home/hkustgz/Us/academic-scraper/log"
XML_SNAPSHOT_PATH = f"{DATA_DIR}/dblp.xml.gz"
PROGRESS_FILE = f"{LOG_DIR}/dblp_fetch_progress.json"

# ClickHouse 配置
CH_HOST = 'localhost'
CH_PORT = 8123
CH_DATABASE = 'academic_db'
CH_TABLE = 'dblp'
CH_USERNAME = 'default'
CH_PASSWORD = ''

# CCF 目录路径
CCF_CATALOG_PATH = "/home/hkustgz/Us/dblp-api/dblp/data/ccf_catalog.csv"
