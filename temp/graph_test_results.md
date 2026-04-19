# 图谱功能测试结果

**测试日期：** 2026-04-19
**更新时间：** 2026-04-19 15:50

## 性能优化结果 ✅

### 问题诊断
- **初始问题：** 数据量过大（2600万条记录/1年）导致查询超时（>60秒）
- **根本原因：** 复杂JOIN操作在ClickHouse全表扫描超时

### 实施的优化

**优化1：时间范围过滤**
- 将默认时间范围从"all"改为"1年"
- 减少数据量：1.2亿 → 2600万条记录

**优化2：期刊关键词过滤**
- 新增 `journal` 参数支持期刊/领域过滤
- 例如：`journal=Nature`、`journal=ArXiv`
- 示例数据：
  - 无过滤：2600万条（1年）→ 超时
  - Scientific Reports：96万条 → <3秒 ✅
  - Nature Communications：16万条 → <1秒 ✅
  - ArXiv：20万条 → <1秒 ✅

**优化3：查询LIMIT调整**
- 有过滤时：LIMIT 500,000
- 确保内存安全和快速响应

### 性能测试结果

| 过滤条件 | 记录数 | 响应时间 | 状态 |
|---------|-------|---------|------|
| 无过滤（1年） | 2600万 | >60秒 | ❌ 超时 |
| journal=Scientific Reports | 96万 | <3秒 | ✅ 正常 |
| journal=Nature Communications | 16万 | <1秒 | ✅ 快速 |
| journal=ArXiv | 20万 | <1秒 | ✅ 快速 |

## API测试

### 基础功能测试

- [x] `/api/graph/authors` - 返回作者节点数据
  - 参数：`max_nodes`, `min_collaborations`, `time_range`, `journal`
  - 状态：✅ 正常
  - 示例：`?max_nodes=5&journal=Scientific Reports`
  - 响应时间：<3秒

- [x] `/api/graph/edges` - 返回合作关系数据
  - 参数：`author_ids`, `min_weight`, `time_range`, `journal`
  - 状态：✅ 正常
  - 响应时间：<2秒

- [x] `/api/graph/stats` - 返回统计数据
  - 参数：`time_range`, `journal`
  - 状态：✅ 正常
  - 示例数据（Scientific Reports）：
    ```json
    {
      "total_papers": 962067,
      "total_authors": 860373,
      "total_collaborations": 31198,
      "avg_collaboration_degree": 1.4,
      "max_collaboration_degree": 571
    }
    ```

- [x] 参数验证正常工作
  - 无效参数返回400错误
  - 缺失参数返回400错误
  - SQL注入防护正常（author_ids验证）

- [x] 缓存机制正常
  - Redis缓存已启用
  - 相同查询命中缓存
  - 缓存键包含time_range和journal参数

## 前端测试

### ⚠️ 需要手动验证

以下功能需要浏览器中手动验证：

- [ ] 图谱正常渲染
  - [ ] 节点正确显示
  - [ ] 链接正确显示
  - [ ] 节点大小反映合作者数量

- [ ] 交互功能
  - [ ] 悬停高亮功能正常
  - [ ] 点击显示详情正常
  - [ ] 缩放/平移功能正常

- [ ] 筛选器
  - [ ] 筛选器联动正常
  - [ ] 时间范围筛选正常
  - [ ] **期刊/领域筛选正常**（新功能 - 需要添加到UI）
  - [ ] 节点数量调整正常

- [ ] UI效果
  - [ ] 粒子背景显示正常
  - [ ] 加载状态显示正常
  - [ ] 错误提示显示正常
  - [ ] Catppuccin Mocha主题应用正常

## 性能测试

### 后端性能

- [x] API响应时间
  - 带journal过滤：<3秒 ✅
  - 不带过滤：超时（需要用户输入期刊）

- [x] 数据集规模
  - 96万记录（Scientific Reports）：流畅 ✅
  - 16万记录（Nature）：非常流畅 ✅
  - 建议：提示用户选择期刊以获得最佳性能

### 前端性能

- [ ] 50节点渲染：需要手动测试
- [ ] 200节点渲染：需要手动测试
- [ ] 500节点渲染：需要手动测试

## 已修复的问题

1. **SQL UNION列数不匹配**（commit: e6fc2e5）
   - 问题：OpenAlex有19列，Semantic有24列
   - 修复：只选择15个共同字段
   - 状态：✅ 已修复

2. **查询超时**（commit: d4c4486, d6aa9d3）
   - 问题：全量数据（1.2亿条）超时
   - 修复：添加时间范围过滤（默认1年）+ 期刊过滤
   - 状态：✅ 已优化

3. **SQL注入风险**
   - 问题：author_ids直接拼接到SQL
   - 修复：添加恶意字符验证（', ', ;, \）
   - 状态：✅ 已修复

## 使用建议

### API调用示例

```bash
# 推荐用法：指定期刊以获得快速响应
curl "http://localhost:8080/api/graph/authors?max_nodes=200&journal=Nature"

# 不同时间范围
curl "http://localhost:8080/api/graph/authors?time_range=1&journal=ArXiv"  # 最近1年
curl "http://localhost:8080/api/graph/authors?time_range=3&journal=ArXiv"  # 最近3年

# 获取统计数据
curl "http://localhost:8080/api/graph/stats?journal=Scientific Reports"
```

### 前端使用建议

1. **默认行为**：
   - 前端应要求用户选择期刊/领域
   - 或提供热门期刊下拉列表

2. **热门期刊推荐**（按论文量）：
   - Scientific Reports (96万)
   - Nature Communications (16万)
   - ArXiv (20万)
   - PLoS ONE (12万)
   - Cancer Research (14万)

3. **错误处理**：
   - 如果用户不选择期刊，提示"为了性能，请选择期刊或领域"

## 下一步工作

### 优先级高

1. **前端集成期刊筛选**
   - 在graph.html中添加期刊选择器
   - 提供热门期刊下拉列表
   - 添加搜索/输入框

2. **浏览器端到端测试**
   - 在浏览器中测试完整功能
   - 验证交互和UI效果

### 优先级中

3. **缓存预热**
   - 预计算热门期刊的统计数据
   - 减少首次加载时间

4. **监控和日志**
   - 添加查询性能监控
   - 记录慢查询

## 总结

✅ **后端API已完成并优化**
- 时间范围过滤（默认1年）
- 期刊关键词过滤
- 快速响应（<3秒）

⚠️ **前端需要集成期刊筛选器**
- 当前：筛选器不支持journal参数
- 需要更新UI以支持期刊选择

🎯 **推荐使用场景**
- 查询特定期刊/领域的合作网络
- 数据量：几十万条记录最佳
- 性能：快速响应（<3秒）

---

**测试人员：** Claude (Subagent-Driven Development)
**审核状态：** 后端API完成，前端待手动测试
**Git提交：**
- e6fc2e5: 修复SQL UNION列数不匹配
- d4c4486: 时间范围优化（默认1年）
- d6aa9d3: 添加期刊关键词过滤
