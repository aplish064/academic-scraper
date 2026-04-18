#!/bin/bash
###############################################################################
# 显示最近的 API 切换通知
###############################################################################

echo "========================================"
echo "📢 API 切换通知历史"
echo "========================================"
echo ""

NOTIFY_FILE="/home/hkustgz/Us/academic-scraper/log/api_notifications.txt"

if [ -f "$NOTIFY_FILE" ]; then
    # 显示最近10条通知
    echo "最近 10 条通知："
    echo ""
    tail -10 "$NOTIFY_FILE" | while IFS='|' read -r timestamp message; do
        echo "📌 $timestamp"
        echo "   $message" | sed 's/\\n/\n   /g'
        echo ""
    done
else
    echo "暂无通知记录（API 尚未切换）"
fi

echo "========================================"
echo "💡 提示：实时监控通知日志："
echo "   tail -f $NOTIFY_FILE"
echo "========================================"
