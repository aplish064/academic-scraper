#!/bin/bash
# 学术数据看板启动脚本（使用虚拟环境）

echo "🚀 启动学术数据看板..."

# 检查虚拟环境
VENV_PATH="../venv/bin/python3"
if [ ! -f "$VENV_PATH" ]; then
    echo "❌ 虚拟环境不存在: $VENV_PATH"
    echo "请先创建虚拟环境: cd .. && python3 -m venv venv"
    exit 1
fi

# 进入dashboard目录
cd "$(dirname "$0")"

# 检查依赖
echo "📦 检查依赖..."
$VENV_PATH -c "
import flask, flask_cors, clickhouse_connect
print('✓ 所有依赖已安装')
" 2>/dev/null

if [ $? -ne 0 ]; then
    echo "❌ 缺少依赖，正在安装..."
    ../venv/bin/pip install flask flask-cors clickhouse_connect
fi

# 检查ClickHouse连接
echo "📡 检查ClickHouse连接..."
if ! clickhouse-client --query "SELECT 1" &> /dev/null; then
    echo "❌ ClickHouse服务未运行，请先启动ClickHouse"
    exit 1
fi

# 检查数据表
echo "📊 检查数据表..."
openalex_count=$(clickhouse-client --query "SELECT count() FROM academic_db.OpenAlex" 2>/dev/null || echo "0")
semantic_count=$(clickhouse-client --query "SELECT count() FROM academic_db.semantic" 2>/dev/null || echo "0")

echo "✓ OpenAlex: $(printf "%'d" $openalex_count) 条记录"
echo "✓ Semantic: $(printf "%'d" $semantic_count) 条记录"
echo ""

# 启动服务
echo "🌐 启动Web服务..."
echo "📍 访问地址: http://localhost:8080"
echo "📡 数据库: ClickHouse"
echo "⏹️  按 Ctrl+C 停止服务"
echo ""

$VENV_PATH api_server.py