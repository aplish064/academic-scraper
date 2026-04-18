#!/bin/bash
###############################################################################
# 测试通知系统
###############################################################################

echo "🧪 测试通知系统..."
echo ""

# 加载通知函数
LOG_DIR="/home/hkustgz/Us/academic-scraper/log"
mkdir -p "$LOG_DIR"

notify_user() {
    local title="$1"
    local message="$2"

    # 1. 写入日志
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 📢 通知: $title - $message" | tee -a "$LOG_DIR/api_rotation_monitor.log"

    # 2. 桌面通知（如果支持）
    if command -v notify-send &> /dev/null; then
        notify-send -u critical -i dialog-warning "$title" "$message" 2>/dev/null &
    fi

    # 3. 屏幕明显输出
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

    # 5. 声音提示（可选）
    if command -v paplay &> /dev/null; then
        paplay /usr/share/sounds/freedesktop/stereo/message.oga 2>/dev/null &
    fi
}

# 测试通知
notify_user \
    "🧪 测试通知" \
    "这是一个测试通知\n当你看到这个消息时，说明通知系统工作正常！\n\n实际 API 切换时你会收到类似的通知。"

echo ""
echo "✅ 测试完成！"
echo ""
echo "如果你："
echo "  - 听到了声音提示"
echo "  - 看到了桌面弹窗（如果支持）"
echo "  - 看到了上面的框形通知"
echo ""
echo "那么通知系统就工作正常！🎉"
