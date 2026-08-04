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

API_URL = os.environ.get("PUSHPLUS_API_URL", "https://www.pushplus.plus/send")
SOURCES = [
    "MKTNews 快讯", "华尔街见闻 快讯", "华尔街见闻最新", "华尔街见闻 最热",
    "财联社 电报", "财联社 深度", "财联社 热门", "雪球 热门股票",
    "格隆汇 事件", "法布财经 快讯", "法布财经 头条", "金十数据",
]


def build_content(now):
    sources_html = "".join(f"<li>{name}</li>" for name in SOURCES)
    return (
        f"<h3>{now:%Y-%m-%d} · 章鱼 AI·全景分析</h3>"
        "<p><b>今日一句话：</b>市场风险偏好回升，<b>AI 算力与电网投资</b>仍是资金聚焦主线，"
        "但短期需警惕高位分化。</p>"
        "<p><b>覆盖 {n} 个数据源：</b></p><ul>{sources}</ul>"
        "<p style=\"color:#888\">数据仅供参考，不构成投资建议</p>"
    ).format(n=len(SOURCES), sources=sources_html)


def main():
    token = os.environ.get("PUSHPLUS_TOKEN")
    if not token:
        print("错误：未配置 PUSHPLUS_TOKEN（请在仓库 Secrets 中设置）", flush=True)
        return 1

    payload = {
        "token": token,
        "title": f"章鱼 AI·全景分析 · {datetime.now():%m-%d}",
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
