# 专利获取器使用指南

## 快速开始

### 1. 初始化 ClickHouse 表

```bash
/home/hkustgz/Us/academic-scraper/venv/bin/python temp/init_patent_table.py
```

### 2. 运行专利获取器

```bash
/home/hkustgz/Us/academic-scraper/venv/bin/python src/patent_fetcher.py
```

### 3. 检查数据完整性

```bash
/home/hkustgz/Us/academic-scraper/venv/bin/python temp/check_patent_duplicates.py
```

### 4. 合并 CSV 文件

```bash
/home/hkustgz/Us/academic-scraper/venv/bin/python temp/merge_patent_csv.py
```

## 配置

编辑 `src/patent_fetcher.py` 中的配置：

```python
# 时间范围
DATASET_START_YEAR = 2023
DATASET_END_YEAR = 1936

# 并发数
MAX_CONCURRENT_DOWNLOADS = 3
MAX_CONCURRENT_REQUESTS = 20

# ClickHouse
CH_HOST = 'localhost'
CH_PORT = 8123
CH_DATABASE = 'academic_db'
```

## 输出文件

```
output/patents/
├── 2026_04_patents.csv
├── 2026_03_patents.csv
└── ...

data/google_patents/
├── 2023/
│   └── google_patents_2023.tsv
└── ...

log/
├── patent_fetch_progress.json
├── patent_fetch.log
└── patent_statistics.json
```

## 断点续传

获取器会自动保存进度，中断后重新运行会从上次位置继续。

## 数据结构

每条记录包含：
- `inventor_name`: 发明人姓名
- `inventor_rank`: 发明人排序
- `patent_id`: 专利号
- `title`: 专利标题
- `applicants`: 申请人列表
- `assignees`: 受让人列表
- `application_date`: 申请日期
- `publication_date`: 公开日期
- `grant_date`: 授权日期
- `patent_type`: 专利类型
- `classifications`: 分类号列表
- `citations`: 引用数
- `family_size`: 同族专利数量
- `source`: 数据源
- `fetched_at`: 获取时间

## 性能优化

- 内存占用：保持 < 8GB
- 下载速度：取决于网络带宽
- 处理速度：约 10,000 行/秒

## 常见问题

**Q: 内存不足？**
A: 减少 `MAX_CONCURRENT_REQUESTS` 或 `BATCH_SIZE`

**Q: API 限流？**
A: 等待重置时间或减少并发数

**Q: 如何重新开始？**
A: 删除 `log/patent_fetch_progress.json`
