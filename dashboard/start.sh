#!/bin/bash
# 学术数据看板启动脚本

echo "📊 学术数据看板启动中..."
echo ""

# 检查Python
if ! command -v python3 &> /dev/null; then
    echo "❌ 错误: 未找到 python3"
    exit 1
fi

# 进入dashboard目录
cd "$(dirname "$0")"

# 检查依赖
echo "📦 检查依赖..."
python3 -c "import flask, flask_cors, pandas" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "📦 安装依赖中..."
    pip3 install -r requirements.txt
fi

# 启动服务
echo ""
echo "🚀 启动服务..."
echo "📍 访问地址: http://localhost:5000"
echo "⏹️  按 Ctrl+C 停止服务"
echo ""

python3 api_server_optimized.py
