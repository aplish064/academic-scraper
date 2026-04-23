-- CNKI文献表（统一表结构，支持期刊、学位、会议、专利）
-- 按作者展开，每行代表一个作者-文献关系
--
-- NOTE: To add table comment after creation:
-- ALTER TABLE academic_db.CNKI MODIFY COMMENT 'CNKI文献表（支持期刊、学位、会议、专利）'

DROP TABLE IF EXISTS academic_db.CNKI;

CREATE TABLE academic_db.CNKI (
    -- 资源类型标识
    resource_type String,           -- 'journal'/'thesis'/'conference'/'patent'

    -- 作者/发明人信息（统一字段）
    author String,                  -- 论文作者 / 专利发明人
    author_id String,               -- 作者ID（如有）
    affiliation String,             -- 作者单位 / 专利申请人

    -- 核心文献信息
    title String,
    doi String,                    -- 专利用申请号
    journal String,                 -- 期刊名 / 学位授予单位 / 会议名称
    publish_date Date,              -- 发表日期 / 学位授予日期 / 会议日期 / 专利申请日

    -- 期刊/会议特有字段
    volume String,                  -- 卷（专利为空）
    issue String,                   -- 期（专利为空）
    pages String,                   -- 页码（专利为空）

    -- 统计信息
    cited_count Int32,              -- 被引次数
    download_count Int32,           -- 下载次数（专利为0）

    -- 内容字段
    keywords Array(String),         -- 关键词
    classification String,          -- 学科分类 / IPC分类号（专利）
    funding String,                 -- 基金信息（专利为空）
    abstract String,                -- 摘要

    -- 学位论文特有字段
    advisor String,                 -- 导师（仅学位论文）
    degree_level String,            -- 学位层次（硕士/博士，仅学位论文）

    -- 专利特有字段
    patent_number String,           -- 专利号（仅专利）
    patent_type String,             -- 专利类型（发明/实用新型/外观，仅专利）
    applicant String,               -- 申请人（仅专利）
    agent String,                   -- 代理人（仅专利）

    -- 通用字段
    rank Int32,                     -- 作者序号
    tag String,                     -- 第一作者/最后作者/其他
    state String,                   -- 状态字段（用于扩展）
    import_time DateTime            -- 导入时间
) ENGINE = MergeTree()
ORDER BY (resource_type, publish_date, doi, rank)
SETTINGS index_granularity = 8192;