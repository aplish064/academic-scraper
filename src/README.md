# Academic Scraper - 源代码目录

## 主要程序文件

### 1. openalex_auto_fetcher_fast.py ⚡
**功能**：OpenAlex 论文自动获取工具（极速版）

**特性**：
- 异步IO + HTTP/2
- 按天获取数据
- 并发处理（默认20并发）
- 自动断点续传
- API限额检测
- 进度实时保存

**使用方法**：
```bash
python3 src/openalex_auto_fetcher_fast.py
```

**配置**：
- `START_DATE`: 开始日期（格式：YYYYMMDD）
- `END_YEAR`: 结束年份
- `MAX_CONCURRENT_REQUESTS`: 并发数（默认20）

**输出**：
- CSV文件：`output/{年}_{月}_openalex_papers.csv`
- 进度文件：`log/openalex_fetch_progress.json`
- 日志文件：`log/openalex_fetch_fast.log`

---

### 2. author_state_finder.py
**功能**：作者状态查找器

**使用方法**：
```bash
python3 src/author_state_finder.py
```

---

### 3. arxiv_fetcher.py
**功能**：ArXiv 论文获取器

**使用方法**：
```bash
python3 src/arxiv_fetcher.py
```

---

### 4. extract_sample_authors.py
**功能**：提取示例作者

**使用方法**：
```bash
python3 src/extract_sample_authors.py
```

---

## 目录结构

```
academic-scraper/
├── src/                    # 主要程序文件
│   ├── openalex_auto_fetcher_fast.py
│   ├── author_state_finder.py
│   ├── arxiv_fetcher.py
│   └── extract_sample_authors.py
├── temp/                   # 临时工具（数据维护）
│   ├── check_duplicates.py
│   ├── merge_csv.py
│   └── README.md
├── output/                 # 输出数据
│   └── *_openalex_papers.csv
├── log/                    # 日志和进度
│   ├── openalex_fetch_fast.log
│   └── openalex_fetch_progress.json
└── README.md              # 本文件
```

---

## 版本说明

- **fast 版本**：使用异步IO，性能优化，推荐使用
- **普通版本**：已弃用，请使用 fast 版本

---

## 更新日志

### 2026-04-13
- ✅ 整理文件结构，移除非 fast 版本
- ✅ 规范文件命名（移除 _fast 后缀）
- ✅ 创建 temp 目录存放工具脚本
- ✅ 添加 API 限额检测
- ✅ 优化内存管理（解决 OOM 问题）
- ✅ 无数据日期不保存到进度文件

---

## 常见问题

### Q: 脚本被 Killed 怎么办？
A: 通常是内存不足，已优化内存管理。如果还有问题，降低 `MAX_CONCURRENT_REQUESTS`。

### Q: API 配额耗尽怎么办？
A: 等待 UTC 午夜重置（约22小时），或注册付费账户。

### Q: 如何断点续传？
A: 脚本会自动读取 `log/openalex_fetch_progress.json`，重新运行即可继续。

### Q: 如何检查数据重复？
A: 运行 `python3 temp/check_duplicates.py`

---

## 开发说明

- Python 3.10+
- 依赖：httpx, tqdm
- 安装：`pip install httpx tqdm`
