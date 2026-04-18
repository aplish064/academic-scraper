#!/bin/bash
###############################################################################
# 快速查看 OpenAlex 抓取状态
###############################################################################

echo "========================================"
echo "📊 OpenAlex 抓取状态"
echo "========================================"
echo ""

# 1. 检查进程状态
echo "🔍 进程状态："
if pgrep -f "python.*openalex_fetcher.py" > /dev/null; then
    pid=$(pgrep -f "python.*openalex_fetcher.py" | head -1)
    echo "  ✅ Fetcher 正在运行 (PID: $pid)"
    ps -p $pid -o pid,ppid,cmd,%mem,%cpu,etime --no-headers | awk '{printf "     CPU: %s%%, 内存: %s%%, 运行时间: %s\n", $5, $4, $6}'
else
    echo "  ❌ Fetcher 未运行"
fi

if pgrep -f "monitor_and_rotate_api.sh" > /dev/null; then
    pid=$(pgrep -f "monitor_and_rotate_api.sh" | head -1)
    echo "  ✅ 监控脚本正在运行 (PID: $pid)"
else
    echo "  ⚠️  监控脚本未运行"
fi

echo ""

# 2. 检查当前使用的 API
echo "🔑 当前 API 配置："
FETCHER_SCRIPT="/home/hkustgz/Us/academic-scraper/src/openalex_fetcher.py"
if [ -f "$FETCHER_SCRIPT" ]; then
    current_key=$(grep "^OPENALEX_API_KEY = " "$FETCHER_SCRIPT" | sed 's/OPENALEX_API_KEY = "\(.*\)".*/\1/')
    current_email=$(grep "^OPENALEX_EMAIL = " "$FETCHER_SCRIPT" | sed 's/OPENALEX_EMAIL = "\(.*\)".*/\1/')
    echo "  API Key: ${current_key:0:8}..."
    echo "  邮箱: $current_email"
fi

echo ""

# 3. 检查 API 轮换索引
API_INDEX_FILE="/home/hkustgz/Us/academic-scraper/log/current_api_index.txt"
if [ -f "$API_INDEX_FILE" ]; then
    index=$(cat "$API_INDEX_FILE")
    echo "🔄 API 轮换索引: $index / 5"
else
    echo "🔄 API 轮换索引: 未初始化"
fi

echo ""

# 4. 显示最近日志
echo "📝 最近日志（最后20行）："
LOG_FILE="/home/hkustgz/Us/academic-scraper/log/openalex_fetch_fast.log"
if [ -f "$LOG_FILE" ]; then
    tail -20 "$LOG_FILE" | sed 's/^/  /'
else
    echo "  (日志文件不存在)"
fi

echo ""

# 5. 显示最近的 API 切换通知
echo "📢 最近的 API 切换通知："
NOTIFY_FILE="/home/hkustgz/Us/academic-scraper/log/api_notifications.txt"
if [ -f "$NOTIFY_FILE" ] && [ -s "$NOTIFY_FILE" ]; then
    echo "  最近 3 条："
    tail -3 "$NOTIFY_FILE" | while IFS='|' read -r timestamp message; do
        ts=$(echo "$timestamp" | cut -d']' -f2)
        echo "  • [$ts] $message"
    done
else
    echo "  暂无切换记录（API 尚未切换）"
fi

echo ""
echo "========================================"
echo "💡 提示："
echo "  - 运行 'tail -f $LOG_FILE' 查看实时日志"
echo "  - 运行 'tail -f /home/hkustgz/Us/academic-scraper/log/api_rotation_monitor.log' 查看监控日志"
echo "  - 运行 '/home/hkustgz/Us/academic-scraper/temp/show_notifications.sh' 查看完整通知历史"
echo "  - 运行 '/home/hkustgz/Us/academic-scraper/temp/test_notification.sh' 测试通知系统"
echo "========================================"
