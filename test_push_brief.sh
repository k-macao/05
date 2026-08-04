#!/usr/bin/env bash
# 验证 push_brief.py（GitHub Actions 推送脚本）→ 假 PushPlus → 假文件
set -u
cd /home/user/05
PY=.venv/bin/python

MOCK_PORT=$($PY -c "import socket;s=socket.socket();s.bind(('127.0.0.1',0));print(s.getsockname()[1]);s.close()")
echo "假PushPlus端口: $MOCK_PORT"
rm -f pushplus_record.json

PORT=$MOCK_PORT RECORD_FILE=/home/user/05/pushplus_record.json $PY mock_pushplus.py >/tmp/mock2.log 2>&1 &
MOCK_PID=$!
sleep 0.6

echo "=== 1. 执行 push_brief.py（模拟 Actions 中的推送命令）==="
PUSHPLUS_TOKEN=fake-token-abc PUSHPLUS_API_URL="http://127.0.0.1:$MOCK_PORT/send" $PY push_brief.py
echo "退出码: $?"

echo ""
echo "=== 2. 假文件内容 ==="
cat pushplus_record.json

echo ""
echo "=== 3. 未配 token 的分支（期望退出码 1）==="
env -u PUSHPLUS_TOKEN -u PUSHPLUS_API_URL $PY push_brief.py
echo "退出码: $?"

kill $MOCK_PID 2>/dev/null
wait 2>/dev/null
echo "(已清理)"
