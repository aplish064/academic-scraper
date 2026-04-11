# 🎓 学术论文自动获取工具

## 🚀 快速开始

```bash
cd /home/apl064/apl/academic-scraper
./start.sh
```

## 📋 三个工具

| 工具 | 数据源 | 速度 | 特色 |
|------|--------|------|------|
| **ArXiv 获取器** | ArXiv | 快 ⚡ | 最新预印本 |
| **OpenAlex 获取器** | OpenAlex | 慢 🐢 | 含引用数据 |

## 🎯 使用场景

### 场景1：使用主启动脚本（推荐）

```bash
./start.sh
```

**交互菜单**：
```
请选择数据源：
  1. ArXiv (快速，论文预印本)
  2. OpenAlex (完整，含引用数据)
  3. 同时运行两个工具
```

### 场景2：直接运行

```bash
# ArXiv 获取
./run_auto.sh

# OpenAlex 获取
./run_openalex.sh
```

### 场景3：后台运行

```bash
# ArXiv 后台
nohup ./run_auto.sh > arxiv.log 2>&1 &

# OpenAlex 后台
nohup ./run_openalex.sh > openalex.log 2>&1 &
```

## 📊 获取范围

### ArXiv 获取器

```
从: 2026年4月10日
到: 2010年12月31日
方向: 往前（倒序）
时间: 约 8-15 小时
存储: 约 2-3 GB
```

### OpenAlex 获取器

```
从: 2026年4月10日
到: 2010年12月31日
方向: 往前（倒序）
时间: 约 40-80 小时
存储: 约 20-50 GB
```

## 📁 输出文件

```
output/
├── 2026_04_arxiv_papers.csv       # ArXiv 数据
├── 2026_03_arxiv_papers.csv
├── ...
├── 2026_04_openalex_papers.csv    # OpenAlex 数据
├── 2026_03_openalex_papers.csv
└── ...
```

## 💡 推荐使用

**快速获取基础数据**：
```bash
./run_auto.sh
```

**获取完整引用数据**：
```bash
./run_openalex.sh
```

**分批获取（推荐）**：
```bash
# 第1步：ArXiv
./run_auto.sh

# 第2步：OpenAlex
./run_openalex.sh
```

## 🔄 断点续传

两个工具都支持断点续传：

```bash
# 中断
^C

# 继续
./run_auto.sh          # ArXiv
./run_openalex.sh      # OpenAlex
```

## 📈 查看进度

```bash
# ArXiv 进度
cat fetch_progress.json

# OpenAlex 进度
cat openalex_fetch_progress.json

# 生成的文件
ls -lh output/*.csv
```

## ⚙️ 配置

### ArXiv 配置

编辑 `src/auto_fetcher.py`：
```python
START_DATE = "20260410"
END_YEAR = 2010
```

### OpenAlex 配置

编辑 `src/openalex_auto_fetcher.py`：
```python
START_DATE = "20260410"
END_YEAR = 2010
```

## 📚 详细文档

- `COMPLETE_GUIDE.md` - 完整使用指南
- `OPENALEX_README.md` - OpenAlex 详细说明
- `QUICKSTART_AUTO.md` - ArXiv 快速开始

## 🎉 特性

- ✅ 自动获取（2010-2026）
- ✅ 倒序获取（从2026年4月10日往前）
- ✅ 断点续传
- ✅ 智能重试
- ✅ 进度记录
- ✅ 按年月组织CSV

## 📞 需要帮助？

查看详细文档或运行 `./start.sh` 开始使用！
