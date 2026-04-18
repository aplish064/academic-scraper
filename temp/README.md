# OpenAlex 抓取管理脚本

## 📁 文件说明

这个 `temp/` 目录包含用于管理 OpenAlex 论文抓取任务的所有脚本。

---

## 🚀 主要脚本

### 1. `monitor_and_rotate_api.sh`
**功能**: OpenAlex API 自动轮换监控脚本（核心脚本）

**作用**:
- 实时监控 openalex_fetcher.py 进程
- 检测 API 配额耗尽（429错误）
- 自动轮换 API key（5个账号循环）
- 自动重启任务
- 发送通知

**运行方式**:
```bash
# 前台运行（用于调试）
/home/hkustgz/Us/academic-scraper/temp/monitor_and_rotate_api.sh

# 后台运行（推荐）
nohup /home/hkustgz/Us/academic-scraper/temp/monitor_and_rotate_api.sh >> /home/hkustgz/Us/academic-scraper/log/monitor_output.log 2>&1 &
```

**状态**: ✅ 当前正在运行

---

### 2. `check_status.sh`
**功能**: 快速查看 OpenAlex 抓取状态

**显示信息**:
- 进程运行状态（CPU、内存、运行时间）
- 当前使用的 API key 和邮箱
- API 轮换索引
- 最近的抓取日志
- 最近的 API 切换通知

**运行方式**:
```bash
/home/hkustgz/Us/academic-scraper/temp/check_status.sh
```

---

### 3. `show_notifications.sh`
**功能**: 显示 API 切换通知历史

**运行方式**:
```bash
/home/hkustgz/Us/academic-scraper/temp/show_notifications.sh
```

**查看实时通知**:
```bash
tail -f /home/hkustgz/Us/academic-scraper/log/api_notifications.txt
```

---

### 4. `test_notification.sh`
**功能**: 测试通知系统

**运行方式**:
```bash
/home/hkustgz/Us/academic-scraper/temp/test_notification.sh
```

**测试效果**:
- 屏幕框形通知
- 桌面弹窗（如果支持）
- 声音提示（如果支持）
- 日志记录

---

## 📊 配置的 API 账号

系统配置了 5 个 OpenAlex API 账号，按顺序自动轮换：

1. **29364625666@qq.com** (索引 0)
2. **13360197039@163.com** (索引 1)
3. **1509901785@qq.com** (索引 2)
4. **17818151056@163.com** (索引 3)
5. **apl064@outlook.com** (索引 4)

---

## 🔔 通知系统

当 API 配额耗尽时，你会收到：

1. **屏幕框形通知** - 醒目的边框提示
2. **桌面弹窗** - 系统通知（如果支持）
3. **声音提示** - 警报音（如果支持）
4. **日志记录** - 所有通知都会记录

---

## 📝 日志文件

所有日志文件位于 `/home/hkustgz/Us/academic-scraper/log/`:

- `openalex_fetch_fast.log` - 抓取任务日志
- `api_rotation_monitor.log` - 监控脚本日志
- `api_notifications.txt` - API 切换通知历史
- `monitor_output.log` - 监控脚本输出
- `current_api_index.txt` - 当前 API 索引

---

## 🔧 管理命令

```bash
# 查看状态
/home/hkustgz/Us/academic-scraper/temp/check_status.sh

# 查看抓取日志
tail -f /home/hkustgz/Us/academic-scraper/log/openalex_fetch_fast.log

# 查看监控日志
tail -f /home/hkustgz/Us/academic-scraper/log/api_rotation_monitor.log

# 查看通知历史
/home/hkustgz/Us/academic-scraper/temp/show_notifications.sh

# 停止监控脚本
pkill -f monitor_and_rotate_api.sh

# 重启监控脚本
nohup /home/hkustgz/Us/academic-scraper/temp/monitor_and_rotate_api.sh >> /home/hkustgz/Us/academic-scraper/log/monitor_output.log 2>&1 &
```

---

## 🛡️ 自动保护机制

监控脚本会检测以下错误并自动切换 API：

- `Rate limit exceeded`
- `429` HTTP 状态码
- `API 配额耗尽`
- `配额已耗尽`
- `RATE_LIMIT_EXCEEDED`

**自动执行流程**:
1. 🛑 停止当前 fetcher 进程
2. 🔄 切换到下一个 API key
3. 💾 备份原配置文件
4. 🚀 重启 fetcher 继续抓取
5. 🔔 发送通知
6. 📝 记录切换日志

---

## 📌 当前状态

- ✅ **OpenAlex Fetcher** 正在运行
- ✅ **监控脚本** 正在运行
- ✅ **API 轮换系统** 已启用
- ✅ **通知系统** 已就绪

---

## 📞 问题排查

如果监控脚本意外停止：

```bash
# 检查进程
ps aux | grep monitor_and_rotate_api

# 重启监控
nohup /home/hkustgz/Us/academic-scraper/temp/monitor_and_rotate_api.sh >> /home/hkustgz/Us/academic-scraper/log/monitor_output.log 2>&1 &

# 检查日志
tail -50 /home/hkustgz/Us/academic-scraper/log/monitor_output.log
```

---

**最后更新**: 2026-04-18
**维护者**: Academic Scraper Team
