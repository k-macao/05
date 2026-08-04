#!/usr/bin/env python3
"""本地/容器运行的章鱼 AI·全景分析 API 与静态文件服务。

启动：PUSHPLUS_TOKEN=... python3 server.py
可选：PORT=4173、PUSHPLUS_TOPIC=xxx
"""
import json
import os
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
SOURCES = [
    "MKTNews 快讯", "华尔街见闻 快讯", "华尔街见闻最新", "华尔街见闻 最热",
    "财联社 电报", "财联社 深度", "财联社 热门", "雪球 热门股票",
    "格隆汇 事件", "法布财经 快讯", "法布财经 头条", "金十数据",
]


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        # The UI and API can be placed behind a preview proxy without stale index.html.
        self.send_header("Cache-Control", "no-store" if self.path in ("/", "/index.html") else "public, max-age=300")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/api/sources":
            return self.send_json(HTTPStatus.OK, SOURCES)
        return super().do_GET()

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/api/run":
            return self.send_json(HTTPStatus.NOT_FOUND, {"message": "接口不存在"})

        token = os.environ.get("PUSHPLUS_TOKEN")
        if not token:
            return self.send_json(HTTPStatus.SERVICE_UNAVAILABLE, {
                "message": "服务端未配置 PUSHPLUS_TOKEN，未执行推送。"
            })

        payload = {
            "token": token,
            "title": "章鱼 AI·全景分析",
            "content": "今日简报已生成。请在章鱼 AI·全景分析服务中接入聚合与 AI 摘要内容。",
            "template": "html",
        }
        topic = os.environ.get("PUSHPLUS_TOPIC")
        if topic:
            payload["topic"] = topic
        try:
            request = Request(
                "https://www.pushplus.plus/send",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urlopen(request, timeout=15) as response:
                result = json.loads(response.read().decode("utf-8"))
            if result.get("code") != 200:
                return self.send_json(HTTPStatus.BAD_GATEWAY, {
                    "message": result.get("msg", "PushPlus 拒绝了推送请求")
                })
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            return self.send_json(HTTPStatus.BAD_GATEWAY, {"message": f"PushPlus 请求失败：{error}"})

        return self.send_json(HTTPStatus.OK, {"message": "简报已推送至 PushPlus"})

    def send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "4173"))
    print(f"Serving 章鱼 AI·全景分析 at http://0.0.0.0:{port}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
