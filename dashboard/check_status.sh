#!/bin/bash
# 服务状态检查脚本

echo "🔍 检查学术数据看板服务状态..."
echo ""

# 检查进程
echo "📊 进程状态:"
ps aux | grep "api_server_fast" | grep python | awk '{printf "  PID: %s, 内存: %.0f MB, CPU: %.1f%%\n", $2, $6/1024, $3}'

echo ""
echo "🌐 端口状态:"
if lsof -i :5000 >/dev/null 2>&1; then
    echo "  ✅ 端口 5000 已就绪"
    echo ""
    echo "🎉 服务已启动！"
    echo "📍 访问地址: http://localhost:5000"
    echo "📍 网络地址: http://$(hostname -I | awk '{print $1}'):5000"
else
    echo "  ⏳ 端口 5000 未就绪"
    echo "  💡 正在加载数据，请稍候..."
fi

echo ""
echo "📈 内存使用:"
free -h | grep "Mem:" | awk '{printf "  已用: %s / 总计: %s\n", $3, $2}'

echo ""
echo "💡 提示: 每30秒运行此脚本检查进度"
