#!/usr/bin/env python3
"""每日简报推送脚本：供 GitHub Actions 定时（12:30 / 19:30 北京时间）或手动触发。

用法：
    PUSHPLUS_TOKEN=xxx python3 push_brief.py
可选：
    PUSHPLUS_TOPIC=xxx       群组 topic
    PUSHPLUS_API_URL=...     覆盖推送地址（测试时指向本地假 PushPlus）

退出码：0 成功，1 未配置 token，2 推送失败。
"""
import json
import os
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import sources

API_URL = os.environ.get("PUSHPLUS_API_URL", "https://www.pushplus.plus/send")
SOURCES = sources.SOURCES


def build_content(now):
    """真实抓取 12 个数据源并渲染 HTML 简报（网络不可用时自动回退内置演示数据）。"""
    try:
        brief = sources.collect_all()
    except Exception:
        brief = {}
    return sources.build_html(brief, now=now)


def main():
    token = os.environ.get("PUSHPLUS_TOKEN")
    if not token:
        print("错误：未配置 PUSHPLUS_TOKEN（请在仓库 Secrets 中设置）", flush=True)
        return 1

    payload = {
        "token": token,
        "title": "章鱼 AI·全景分析",
        "content": build_content(datetime.now()),
        "template": "html",
    }
    topic = os.environ.get("PUSHPLUS_TOPIC")
    if topic:
        payload["topic"] = topic

    try:
        request = Request(
            API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=15) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
        print(f"错误：PushPlus 请求失败：{error}", flush=True)
        return 2

    if result.get("code") != 200:
        print(f"错误：PushPlus 拒绝：{result.get('msg', result)}", flush=True)
        return 2

    print(f"推送成功：{payload['title']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
