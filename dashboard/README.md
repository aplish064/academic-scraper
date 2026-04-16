# 学术数据看板

一个简洁、现代的学术论文数据可视化看板，采用蓝白配色方案。

## 功能特点

- **📊 实时统计**: 论文总数、作者数、期刊数、高被引论文等
- **📈 趋势图表**: 按日期展示论文发布趋势
- **🔥 高被引论文**: 展示引用量最高的论文
- **📋 论文列表**: 可筛选的最新论文表格
- **🔍 多维度筛选**: 按时间、作者类型、引用数筛选
- **💾 数据导出**: 支持导出筛选后的数据为CSV

## 设计特色

- **简洁蓝白风格**: 清新专业的学术风格
- **优雅的字体组合**: Playfair Display + IBM Plex Sans + JetBrains Mono
- **流畅的动画**: 数字计数动画、卡片悬浮效果
- **响应式设计**: 支持桌面和移动设备
- **高性能**: 数据缓存机制，快速加载

## 快速开始

### 方法1: 使用启动脚本（推荐）

```bash
cd /home/apl064/apl/academic-scraper/dashboard
./start.sh
```

### 方法2: 手动启动

```bash
# 1. 安装依赖
pip3 install -r requirements.txt

# 2. 启动服务
python3 api_server.py
```

### 访问看板

服务启动后，在浏览器中访问：

```
http://localhost:5000
```

## API接口

后端提供以下API接口：

| 接口 | 说明 |
|------|------|
| `GET /` | 主页 |
| `GET /api/papers` | 获取论文列表（支持分页） |
| `GET /api/statistics` | 获取统计信息 |
| `GET /api/top-papers` | 获取高被引论文 |
| `GET /api/papers/by-date` | 按日期统计论文数 |

### 分页参数

```
GET /api/papers?page=1&per_page=100
```

## 筛选功能

看板支持以下筛选条件：

- **时间范围**: 全部时间、最近7天、最近30天、最近90天
- **作者类型**: 全部作者、第一作者、最后作者、其他作者
- **最低引用**: 全部、≥10次、≥50次、≥100次

## 数据来源

数据来自 `/output/openalex/` 目录下的CSV文件，由 `openalex_fetcher.py` 生成。

## 技术栈

- **前端**: HTML5 + CSS3 + Vanilla JavaScript
- **后端**: Flask + Pandas
- **样式**: 自定义CSS（无框架依赖）
- **字体**: Google Fonts（Playfair Display、IBM Plex Sans、JetBrains Mono）

## 性能优化

- **数据缓存**: 5分钟缓存机制，减少重复加载
- **分页加载**: 支持大规模数据的分页查询
- **懒加载**: 按需加载数据

## 自定义配置

可以在 `api_server.py` 中修改以下配置：

```python
# 缓存时长（秒）
CACHE_DURATION = 300

# 服务端口
app.run(host='0.0.0.0', port=5000, debug=True)
```

## 故障排除

### 数据加载失败

确保CSV文件存在于正确路径：
```
/output/openalex/YYYY/MM/YYYY-MM-DD.csv
```

### 端口冲突

如果5000端口被占用，可以修改端口：
```python
app.run(host='0.0.0.0', port=8000, debug=True)
```

### 依赖安装失败

确保使用Python 3.8+：
```bash
python3 --version
```

## 未来改进

- [ ] 添加更多图表类型（饼图、散点图等）
- [ ] 支持更多筛选条件
- [ ] 添加数据对比功能
- [ ] 支持导出为PDF报告
- [ ] 添加数据预警功能

## 许可证

MIT License
