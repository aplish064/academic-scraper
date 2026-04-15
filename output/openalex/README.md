# OpenAlex 数据字段说明

## CSV 文件结构

数据按日期组织：`{year}/{month}/{date}.csv`

## 字段说明

### 基本信息

| 字段 | 说明 | 示例 |
|------|------|------|
| `author_id` | OpenAlex 作者 ID | `5100374847` |
| `author` | 作者姓名 | `Shijie Wang` |
| `uid` | OpenAlex 论文 ID | `https://openalex.org/W4406003536` |
| `doi` | 论文 DOI | `https://doi.org/10.1038/s41467-024-52768-7` |
| `title` | 论文标题 | `Electronic structure formed by...` |
| `rank` | 作者排序 | `1` (第一作者) |
| `journal` | 期刊名称 | `Nature Communications` |
| `citation_count` | 引用数 | `454` |
| `tag` | 作者角色 | `第一作者` / `最后作者` / `其他` |
| `state` | 作者状态 (待补充) | 空 |

### 机构信息（论文发表时）

| 字段 | 说明 | 示例 |
|------|------|------|
| `institution_id` | 机构 OpenAlex ID | `2799798094` |
| `institution_name` | 机构名称 | `UCLA Health` |
| `institution_country` | 机构国家代码 | `US` |
| `institution_type` | 机构类型 | `education` / `company` / `funder` |
| `raw_affiliation` | 原始归属字符串 | `Neurobiology UCLA Los Angeles CA` |

### 质量指标

| 字段 | 说明 | 示例 |
|------|------|------|
| `fwci` | 领域加权影响因子 | `1.23` (≥1 表示高于平均水平) |
| `citation_percentile` | 引用百分位 | `95` (Top 5%) |
| `primary_topic` | 主要研究主题 | `Migraine and Headache Studies` |
| `is_retracted` | 是否撤稿 | `false` |

## 机构类型说明

- `education`: 教育机构（大学、学院）
- `company`: 公司
- `funder`: 资助机构
- `healthcare`: 医疗机构
- `government`: 政府机构
- `research`: 研究机构
- `archive`: 档案馆
- `other`: 其他

## 数据来源

- OpenAlex API: https://api.openalex.org
