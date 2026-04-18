#!/bin/bash
###############################################################################
# OpenAlex API 自动轮换监控脚本
# 功能：
#   1. 监控 openalex_fetcher.py 进程
#   2. 检测 API 配额耗尽（429错误）
#   3. 自动轮换 API key
#   4. 重启任务
###############################################################################

# 配置
FETCHER_SCRIPT="/home/hkustgz/Us/academic-scraper/src/openalex_fetcher.py"
LOG_DIR="/home/hkustgz/Us/academic-scraper/log"
LOG_FILE="$LOG_DIR/openalex_fetch_fast.log"
MONITOR_LOG="$LOG_DIR/api_rotation_monitor.log"
PID_FILE="$LOG_DIR/fetcher.pid"
API_INDEX_FILE="$LOG_DIR/current_api_index.txt"

# API keys 列表（按顺序轮换）
declare -a API_KEYS=(
    "toZBE5tNglH7oDydLefrKc:29364625666@qq.com"
    "zF5B0bERxfXCZsPF1P5TiY:13360197039@163.com"
    "Q5QcudPogcFTfvV7vFOH1r:1509901785@qq.com"
    "2ZiX5542GoZp9VYwHv2jPj:17818151056@163.com"
    "1KyA5m5gjQxBgFetDtko9Q:apl064@outlook.com"
)

TOTAL_APIS=${#API_KEYS[@]}

# 初始化
mkdir -p "$LOG_DIR"

# 日志函数
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$MONITOR_LOG"
}

# 明显的通知函数
notify_user() {
    local title="$1"
    local message="$2"

    # 1. 写入日志
    log "📢 通知: $title - $message"

    # 2. 桌面通知（如果支持）
    if command -v notify-send &> /dev/null; then
        notify-send -u critical -i dialog-warning "$title" "$message" 2>/dev/null
    fi

    # 3. 屏幕明显输出（使用颜色）
    echo ""
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║  🚨🚨🚨 API 自动切换通知 🚨🚨🚨                               ║"
    echo "╠════════════════════════════════════════════════════════════════╣"
    echo "║  $title"
    echo "║  $message"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo ""

    # 4. 记录到单独的通知文件
    local notify_file="$LOG_DIR/api_notifications.txt"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $title | $message" >> "$notify_file"

    # 5. 尝试声音提示（可选）
    if command -v paplay &> /dev/null; then
        paplay /usr/share/sounds/freedesktop/stereo/message.oga 2>/dev/null &
    fi
}

# 获取当前使用的 API 索引
get_current_api_index() {
    if [ -f "$API_INDEX_FILE" ]; then
        cat "$API_INDEX_FILE"
    else
        echo 0
    fi
}

# 保存当前 API 索引
save_api_index() {
    echo $1 > "$API_INDEX_FILE"
}

# 获取下一个 API key
get_next_api() {
    local current_index=$(get_current_api_index)
    local next_index=$(( (current_index + 1) % TOTAL_APIS ))
    save_api_index $next_index

    local api_info="${API_KEYS[$next_index]}"
    local api_key=$(echo $api_info | cut -d':' -f1)
    local api_email=$(echo $api_info | cut -d':' -f2)

    echo "$api_key:$api_email"
}

# 替换 API key
replace_api_key() {
    local old_api_index=$(get_current_api_index)
    local new_api=$(get_next_api)
    local new_key=$(echo $new_api | cut -d':' -f1)
    local new_email=$(echo $new_api | cut -d':' -f2)
    local new_api_index=$(get_current_api_index)

    log "🔄 替换 API key..."
    log "   从索引 $old_api_index 切换到索引 $new_api_index"
    log "   新 API Key: ${new_key:0:8}..."
    log "   新邮箱: $new_email"

    # 备份原文件
    cp "$FETCHER_SCRIPT" "${FETCHER_SCRIPT}.backup_$(date +%Y%m%d_%H%M%S)"

    # 替换 API key 和邮箱
    sed -i "s/^OPENALEX_API_KEY = \".*\"/OPENALEX_API_KEY = \"$new_key\"  # 您的 API Key/" "$FETCHER_SCRIPT"
    sed -i "s/^OPENALEX_EMAIL = \".*\"/OPENALEX_EMAIL = \"$new_email\"  # 您的邮箱/" "$FETCHER_SCRIPT"

    log "✅ API key 已更新"

    # 发送明显通知
    notify_user \
        "⚠️  OpenAlex API 已自动切换！" \
        "旧 API (索引$old_api_index) 配额耗尽 → 已切换到 API (索引$new_api_index)\n邮箱: $new_email\nKey: ${new_key:0:12}..."
}

# 停止现有进程
stop_fetcher() {
    local pid=$(pgrep -f "python.*openalex_fetcher.py" | head -1)
    if [ -n "$pid" ]; then
        log "🛑 停止现有进程 (PID: $pid)"
        kill $pid
        sleep 3

        # 强制杀死如果还在运行
        if ps -p $pid > /dev/null 2>&1; then
            log "⚠️  强制停止进程"
            kill -9 $pid
            sleep 2
        fi
    else
        log "ℹ️  没有运行中的 fetcher 进程"
    fi
}

# 启动 fetcher
start_fetcher() {
    log "🚀 启动 openalex_fetcher.py..."

    cd /home/hkustgz/Us/academic-scraper

    # 启动进程并记录 PID（使用虚拟环境中的 python）
    nohup /home/hkustgz/Us/academic-scraper/venv/bin/python "$FETCHER_SCRIPT" >> "$LOG_FILE" 2>&1 &
    local pid=$!
    echo $pid > "$PID_FILE"

    log "✅ Fetcher 已启动 (PID: $pid)"
    log "   日志文件: $LOG_FILE"
}

# 检查进程是否在运行
is_fetcher_running() {
    pgrep -f "python.*openalex_fetcher.py" > /dev/null
    return $?
}

# 监控日志中的错误
monitor_logs() {
    log "👀 开始监控日志文件..."

    # 获取日志文件当前大小
    if [ -f "$LOG_FILE" ]; then
        current_size=$(stat -f%z "$LOG_FILE" 2>/dev/null || stat -c%s "$LOG_FILE" 2>/dev/null)
    else
        current_size=0
    fi

    while true; do
        sleep 10

        # 检查进程是否还在运行
        if ! is_fetcher_running; then
            log "⚠️  Fetcher 进程已停止，尝试重启..."
            start_fetcher
            continue
        fi

        # 检查日志文件是否有新内容
        if [ -f "$LOG_FILE" ]; then
            new_size=$(stat -f%z "$LOG_FILE" 2>/dev/null || stat -c%s "$LOG_FILE" 2>/dev/null)

            if [ "$new_size" -gt "$current_size" ]; then
                # 读取新增的日志内容
                new_content=$(tail -c +$((current_size + 1)) "$LOG_FILE")

                # 检查是否包含 API 配额耗尽的错误
                if echo "$new_content" | grep -qi "rate limit exceeded\|429\|API 配额耗尽\|配额已耗尽\|RATE_LIMIT_EXCEEDED"; then
                    log "🚨 检测到 API 配额耗尽！"
                    log "   触发日志行："
                    echo "$new_content" | tail -20 >> "$MONITOR_LOG"

                    # 发送警告通知
                    notify_user \
                        "⛔ API 配额耗尽检测！" \
                        "检测到 OpenAlex API 配额已用完\n正在自动切换到下一个 API..."

                    # 停止进程
                    stop_fetcher

                    # 替换 API key（这会触发另一个通知）
                    replace_api_key

                    # 重启进程
                    start_fetcher

                    # 发送完成通知
                    notify_user \
                        "✅ API 切换完成" \
                        "新 API 已启用，抓取任务已重启\n继续监控中..."

                    # 等待一段时间避免频繁切换
                    log "⏳ 等待 30 秒后继续监控..."
                    sleep 30
                fi

                current_size=$new_size
            fi
        fi
    done
}

# 主函数
main() {
    log "========================================"
    log "🎯 OpenAlex API 轮换监控脚本启动"
    log "========================================"
    log "API 总数: $TOTAL_APIS"
    log "当前 API 索引: $(get_current_api_index)"
    log "监控脚本: $0"
    log "Fetcher 脚本: $FETCHER_SCRIPT"
    log "========================================"

    # 检查 fetcher 是否已经在运行
    if is_fetcher_running; then
        log "✅ Fetcher 正在运行，开始监控..."
    else
        log "⚠️  Fetcher 未运行，启动中..."
        start_fetcher
    fi

    # 开始监控
    monitor_logs
}

# 信号处理
trap 'log "⚠️  收到中断信号，退出..."; exit 0' INT TERM

# 启动
main
