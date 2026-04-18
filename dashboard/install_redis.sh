#!/bin/bash
# Redis安装脚本

echo "🔧 检查Redis安装状态..."

if command -v redis-server &> /dev/null; then
    echo "✓ Redis已安装"
    redis-server --version
else
    echo "📦 开始安装Redis..."

    # 检测系统类型
    if [ -f /etc/debian_version ]; then
        # Debian/Ubuntu
        echo "  检测到Debian/Ubuntu系统"
        sudo apt update
        sudo apt install -y redis-server
        sudo systemctl start redis
        sudo systemctl enable redis
    elif [ -f /etc/redhat-release ]; then
        # RHEL/CentOS
        echo "  检测到RHEL/CentOS系统"
        sudo yum install -y redis
        sudo systemctl start redis
        sudo systemctl enable redis
    elif command -v brew &> /dev/null; then
        # macOS
        echo "  检测到macOS系统"
        brew install redis
        brew services start redis
    else
        echo "❌ 不支持的系统，请手动安装Redis"
        exit 1
    fi
fi

echo ""
echo "🧪 测试Redis连接..."
if redis-cli ping &> /dev/null; then
    echo "✓ Redis运行正常！"
    redis-cli ping
else
    echo "❌ Redis未运行，尝试启动..."
    if [ -f /etc/debian_version ]; then
        sudo systemctl start redis
    elif command -v brew &> /dev/null; then
        brew services start redis
    fi

    sleep 2
    if redis-cli ping &> /dev/null; then
        echo "✓ Redis启动成功！"
    else
        echo "❌ Redis启动失败，请手动检查"
        exit 1
    fi
fi

echo ""
echo "✅ Redis安装完成！"
echo ""
echo "📦 安装Python Redis客户端..."
cd "$(dirname "$0")"
../venv/bin/pip install redis

echo ""
echo "🎉 所有依赖已安装！现在可以启动服务了："
echo "   cd dashboard && ../venv/bin/python3 api_server.py"
