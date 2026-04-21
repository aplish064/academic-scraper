#!/bin/bash
# DBLP Streaming Fetcher - Run Script

echo "=== DBLP Streaming Fetcher ==="
echo ""

# Ensure proxy is running
if ! pgrep -x mihomo > /dev/null; then
    echo "Starting proxy..."
    /home/hkustgz/Us/clash/bin/mihomo -d /home/hkustgz/Us/clash/config -f /home/hkustgz/Us/clash/config/config.yaml > /tmp/mihomo.log 2>&1 &
    sleep 2
fi

cd /home/hkustgz/Us/academic-scraper
echo "Starting streaming fetcher..."
echo ""

# Run streaming fetcher with virtual environment
/home/hkustgz/Us/academic-scraper/venv/bin/python src/dblp_fetcher_streaming.py
