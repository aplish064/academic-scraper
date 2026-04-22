# 学术数据看板

一个高性能的学术论文数据可视化看板，基于ClickHouse数据库。

## 📋 目录

- [功能特点](#功能特点)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [ClickHouse安装](#clickhouse安装)
- [数据导入](#数据导入)
- [配置说明](#配置说明)
- [API接口](#api接口)
- [文件结构](#文件结构)
- [故障排除](#故障排除)

## 功能特点

- **📊 实时统计**: 论文总数、作者数、期刊数、高被引论文等
- **📈 趋势图表**: 按日期展示论文发布趋势
- **🔥 高被引论文**: 展示引用量最高的论文
- **🔍 多维度筛选**: 按时间、作者类型、引用数筛选
- **⚡ 高性能查询**: 基于ClickHouse的毫秒级响应
- **📈 大数据支持**: 支持千万级数据查询
- **🏷️ 数据源切换**: 支持OpenAlex、DBLP、Semantic Scholar多数据源切换
- **💾 Redis缓存**: 提升数据查询性能

## 支持的数据源

- **OpenAlex**: 完整的论文、引用和机构信息
- **DBLP**: 计算机科学论文，包含CCF评级和会议类型
- **Semantic Scholar**: 论文和引用信息
- **arXiv**: 预印本论文，包含学科分类和时间趋势分析

## 技术栈

- **前端**: HTML5 + CSS3 + Vanilla JavaScript
- **后端**: Flask + ClickHouse + Redis
- **数据库**: ClickHouse (列式存储，高性能分析)
- **缓存**: Redis (数据缓存，提升查询性能)
- **样式**: 自定义CSS（无框架依赖）

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动服务

```bash
./start.sh
```

### 3. 访问看板

```
http://localhost:5000
```

## ClickHouse安装

### Ubuntu/Debian系统

```bash
# 添加ClickHouse仓库
echo "deb https://packages.clickhouse.com/deb stable main" | sudo tee \
    /etc/apt/sources.list.d/clickhouse.list

# 安装ClickHouse
sudo apt update
sudo apt install -y clickhouse-server clickhouse-client

# 启动服务
sudo systemctl start clickhouse-server
sudo systemctl enable clickhouse-server

# 验证安装
clickhouse-client --query "SELECT 1"
```

### 配置远程访问

```bash
# 编辑配置文件
sudo nano /etc/clickhouse-server/config.xml

# 找到并修改这行
<listen_host>::</listen_host>

# 重启服务
sudo systemctl restart clickhouse-server

# 开放防火墙端口
sudo ufw allow 8123/tcp
sudo ufw allow 9000/tcp
```

### 其他系统

**CentOS/RHEL:**
```bash
sudo yum install -y clickhouse-server clickhouse-client
```

**Docker:**
```bash
docker run -d --name clickhouse \
  -p 8123:8123 -p 9000:9000 \
  clickhouse/clickhouse-server:24.3
```

## 数据导入

### 1. 测试ClickHouse连接

```bash
python3 ../temp/test_clickhouse.py
```

### 2. 导入CSV数据

```bash
# 测试导入（前5个文件）
python3 ../temp/clickhouse_import.py 5

# 导入所有数据
python3 ../temp/clickhouse_import.py
```

### 3. 验证导入结果

```bash
# 查看数据记录数
clickhouse-client --query "SELECT count() FROM academic_db.papers"

# 查看样本数据
clickhouse-client --query "SELECT * FROM academic_db.papers LIMIT 5"
```

## 配置说明

编辑 `config.py` 修改配置：

```python
# ClickHouse配置
CLICKHOUSE_CONFIG = {
    'host': 'localhost',        # ClickHouse主机
    'port': 8123,               # HTTP端口
    'database': 'academic_db',  # 数据库名
    'username': 'default',      # 用户名
    'password': '',             # 密码
    'table': 'papers'           # 表名
}

# Flask服务配置
FLASK_CONFIG = {
    'host': '0.0.0.0',  # 监听地址
    'port': 5000,       # 端口
    'debug': False      # 调试模式
}
```

### 环境变量配置

也可以通过环境变量配置：

```bash
export CLICKHOUSE_HOST=localhost
export CLICKHOUSE_PORT=8123
export CLICKHOUSE_DATABASE=academic_db
export CLICKHOUSE_USER=default
export CLICKHOUSE_PASSWORD=
export CLICKHOUSE_TABLE=papers
```

## API接口

| 接口 | 说明 |
|------|------|
| `GET /` | 主页 |
| `GET /api/aggregated` | 获取聚合数据 |
| `GET /api/health` | 健康检查 |
| `GET /api/refresh` | 刷新缓存 |
| `GET /api/data-sources` | 获取支持的数据源 |
| `POST /api/switch-data-source` | 切换数据源 |

### 数据源参数

- `source=all`: 聚合所有数据源（OpenAlex + Semantic + DBLP + arXiv）
- `source=openalex`: 仅OpenAlex数据
- `source=semantic`: 仅Semantic Scholar数据
- `source=dblp`: 仅DBLP数据
- `source=arxiv`: 仅arXiv数据（包含分类分布和时间趋势）

### 数据结构

`/api/aggregated` 返回的数据结构：

```json
{
  "papers_by_date": {},
  "citations_distribution": {},
  "author_types": {},
  "top_journals": {},
  "top_countries": {},
  "institution_types": {},
  "fwci_distribution": {},
  "top_papers": [],
  "statistics": {
    "total_papers": 0,
    "unique_authors": 0,
    "unique_journals": 0,
    "unique_institutions": 0,
    "high_citations": 0,
    "avg_fwci": 0
  }
}
```

## 文件结构

```
dashboard/
├── api_server.py         # 主API服务
├── config.py             # 配置文件
├── index.html            # 前端页面
├── chart.umd.js         # 图表库
├── start.sh             # 启动脚本
├── requirements.txt     # Python依赖
└── README.md            # 本文档
```

### 文件说明

- **api_server.py**: Flask API服务器，提供数据接口
- **config.py**: 集中配置文件
- **index.html**: 前端页面
- **start.sh**: 一键启动脚本
- **requirements.txt**: Python依赖列表

## 故障排除

### ClickHouse连接失败

```bash
# 检查ClickHouse服务
sudo systemctl status clickhouse-server

# 启动ClickHouse
sudo systemctl start clickhouse-server

# 测试连接
curl http://localhost:8123/ping

# 查看日志
sudo tail -f /var/log/clickhouse-server/clickhouse-server.log
```

### 数据未导入

```bash
# 测试数据库连接
python3 ../temp/test_clickhouse.py

# 查看数据记录
clickhouse-client --query "SELECT count() FROM academic_db.papers"

# 检查表是否存在
clickhouse-client --query "SHOW TABLES FROM academic_db"
```

### 端口冲突

修改 `config.py` 中的端口配置：
```python
FLASK_CONFIG = {
    'port': 8000  # 改为其他端口
}
```

### 依赖安装失败

使用清华源：
```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple/
```

### 内存不足

如果导入时出现内存不足：
```bash
# 分批导入，每次只处理指定数量的文件
python3 ../temp/clickhouse_import.py 10
```

## 性能优势

相比CSV版本：
- **查询速度**: 从秒级提升到毫秒级
- **数据规模**: 支持千万级数据
- **并发性能**: 支持多用户同时查询
- **内存占用**: 大幅降低内存使用
- **实时查询**: 无需预聚合，支持任意查询

## 维护管理

### 后台运行

```bash
# 使用nohup后台运行
nohup ./start.sh > server.log 2>&1 &

# 查看日志
tail -f server.log

# 停止服务
pkill -f api_server.py
```

### 系统服务

创建systemd服务：
```bash
sudo nano /etc/systemd/system/academic-dashboard.service
```

内容：
```ini
[Unit]
Description=Academic Dashboard Service
After=network.target clickhouse.service

[Service]
Type=simple
User=your-username
WorkingDirectory=/path/to/dashboard
ExecStart=/usr/bin/python3 /path/to/dashboard/api_server.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启动服务：
```bash
sudo systemctl daemon-reload
sudo systemctl enable academic-dashboard
sudo systemctl start academic-dashboard
```

## 数据更新

### 增量导入

直接运行导入脚本会自动追加新数据：
```bash
python3 ../temp/clickhouse_import.py
```

### 重新导入

```bash
# 清空数据
clickhouse-client --query "TRUNCATE TABLE academic_db.papers"

# 重新导入
python3 ../temp/clickhouse_import.py
```

## 获取帮助

- ClickHouse文档：https://clickhouse.com/docs
- Python客户端：https://github.com/ClickHouse/clickhouse-connect

## 许可证

MIT License
