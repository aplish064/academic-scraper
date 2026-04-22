# DBLP数据维护工具使用指南

## 概述

`src/dblp_maintenance.py` 是一个统一的DBLP数据维护工具，整合了之前分散在`temp/`目录中的各种功能。

## 功能

### 1. CSrankings字段补充
为数据库中的现有记录补充CSrankings信息（机构、主页、Scholar ID、ORCID）。

### 2. 字段修复
修复venue_type和ccf_class等字段。

### 3. 数据验证
验证数据完整性和统计信息。

## 使用方法

### 查看帮助

```bash
python src/dblp_maintenance.py --help
```

### 1. 补充CSrankings字段

```bash
# 基本使用
python src/dblp_maintenance.py csrankings

# 指定并发线程数
python src/dblp_maintenance.py csrankings --workers 20

# 试运行（不写入数据库）
python src/dblp_maintenance.py csrankings --dry-run

# 指定CSrankings文件路径
python src/dblp_maintenance.py csrankings --csrankings-path /path/to/csrankings.csv
```

**功能说明**：
- 从CSrankings CSV文件加载作者信息
- 查询数据库中这些作者的记录
- 为缺少CSrankings字段的记录补充数据
- 支持并发处理，提高速度
- 支持`--dry-run`模式预览更改

### 2. 修复字段

```bash
python src/dblp_maintenance.py fix-fields
```

**功能说明**：
- 根据dblp_key前缀推断正确的venue_type
- 从venue名称匹配CCF等级
- 使用ALTER TABLE UPDATE批量更新

### 3. 验证数据

```bash
python src/dblp_maintenance.py validate
```

**输出信息**：
- 总记录数统计
- 关键字段完整性检查
- CSrankings字段填充情况
- CCF等级分布
- venue_type分布

## 集成说明

### 与fetcher的关系

**CSrankings功能已集成到fetcher中**：

- `src/dblp_fetcher.py` 在导入新数据时自动使用CSrankings数据
- `src/streaming/author_matcher.py` 在处理每条记录时自动匹配CSrankings信息

**维护工具的作用**：

- 用于批处理**已存在的数据**
- 补充之前未填充的字段
- 数据质量验证和修复

### 数据流程

```
新数据导入:
  DBLP XML → dblp_fetcher.py → 使用CSrankings数据 → 写入数据库

已有数据维护:
  数据库记录 → dblp_maintenance.py → 补充CSrankings字段 → 更新数据库
```

## 替代的temp目录脚本

以下temp目录中的脚本功能已被整合：

| 旧脚本 | 新工具命令 | 说明 |
|--------|-----------|------|
| `temp/dblp_csrankings_only.py` | `dblp_maintenance.py csrankings` | CSrankings字段补充 |
| `temp/dblp_batch_csrankings_only.py` | `dblp_maintenance.py csrankings --workers N` | 并发CSrankings补充 |
| `temp/fix_dblp_venuetype_and_ccf.py` | `dblp_maintenance.py fix-fields` | 字段修复 |
| `temp/test_csrankings_integration.py` | `dblp_maintenance.py validate` | 数据验证 |

## 性能建议

### CSrankings补充

- **小数据集**（< 100万记录）: `--workers 10`
- **大数据集**（> 100万记录）: `--workers 20`
- **初次运行**: 建议使用`--dry-run`预览

### 字段修复

- 需要启用ClickHouse轻量级更新
- 可能需要较长时间（取决于数据量）
- 建议在低峰期运行

## 示例工作流

### 完整的维护流程

```bash
# 1. 验证当前数据状态
python src/dblp_maintenance.py validate

# 2. 补充CSrankings字段（试运行）
python src/dblp_maintenance.py csrankings --dry-run

# 3. 补充CSrankings字段（正式运行）
python src/dblp_maintenance.py csrankings --workers 20

# 4. 修复字段
python src/dblp_maintenance.py fix-fields

# 5. 再次验证
python src/dblp_maintenance.py validate
```

## 故障排除

### CSrankings补充失败

**问题**: 找不到需要更新的记录

**原因**: 所有记录都已填充

**解决**: 运行`validate`命令检查填充率

### 字段修复失败

**问题**: ALTER TABLE UPDATE报错

**原因**: ClickHouse未启用轻量级更新

**解决**:
```sql
ALTER TABLE dblp MODIFY SETTING enable_block_offset_column = 1
```

### 并发问题

**问题**: 过多线程导致数据库连接失败

**解决**: 减少`--workers`参数值

## 配置

### CSrankings数据源

默认路径: `data/csrankings.csv`

可通过`--csrankings-path`参数指定其他路径。

### ClickHouse连接

配置文件: `dashboard/config.py`

修改配置:
```python
CLICKHOUSE_CONFIG = {
    'host': 'localhost',
    'port': 8123,
    'database': 'academic_db',
    'username': 'default',
    'password': ''
}
```

## 维护计划

建议定期运行维护任务：

- **每月**: 运行`validate`检查数据质量
- **每季度**: 运行`csrankings`补充新作者的CSrankings信息
- **按需**: 运行`fix-fields`修复发现的问题
