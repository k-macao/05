#!/usr/bin/env python3
"""本地/容器运行的章鱼 AI·全景分析 API 与静态文件服务。

启动：PUSHPLUS_TOKEN=... python3 server.py
可选：PORT=4173
"""
import json
import os
import time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import sources

ROOT = Path(__file__).resolve().parent
# 推送地址可用环境变量覆盖，默认走真实 PushPlus；测试时指向本地假服务。
PUSHPLUS_API_URL = os.environ.get("PUSHPLUS_API_URL", "https://www.pushplus.plus/send")
SOURCES = sources.SOURCES

# /api/brief 的结果缓存（抓取 18 个源较慢，5 分钟内不重复抓取）。
_BRIEF_CACHE = {"at": 0.0, "data": None}
_BRIEF_TTL = 300


def get_brief():
    """抓取并缓存全量简报数据：{name: [item, ...]}。"""
    now = time.time()
    if _BRIEF_CACHE["data"] is not None and now - _BRIEF_CACHE["at"] < _BRIEF_TTL:
        return _BRIEF_CACHE["data"]
    data = sources.collect_all()
    _BRIEF_CACHE["at"] = now
    _BRIEF_CACHE["data"] = data
    return data


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
        path = self.path.split("?", 1)[0]
        if path == "/api/sources":
            return self.send_json(HTTPStatus.OK, SOURCES)
        if path == "/api/brief":
            try:
                brief = get_brief()
            except Exception as error:  # 抓取异常也返回可用结果
                brief = {"error": str(error)}
            return self.send_json(HTTPStatus.OK, brief)
        return super().do_GET()

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/api/run":
            return self.send_json(HTTPStatus.NOT_FOUND, {"message": "接口不存在"})

        token = os.environ.get("PUSHPLUS_TOKEN")
        if not token:
            return self.send_json(HTTPStatus.SERVICE_UNAVAILABLE, {
                "message": "服务端未配置 PUSHPLUS_TOKEN，未执行推送。"
            })
        token = token.strip()  # 防止环境变量混入空白字符

        # 真实抓取 18 个数据源并生成 HTML 简报（网络不可用时自动回退内置演示数据）。
        try:
            brief = get_brief()
        except Exception:
            brief = sources.collect_all()
        content = sources.build_html(brief)

        payload = {
            "token": token,
            "title": "章鱼 AI·全景分析",
            "content": content,
            "template": "html",
        }
        try:
            request = Request(
                PUSHPLUS_API_URL,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urlopen(request, timeout=15) as response:
                result = json.loads(response.read().decode("utf-8"))
            if result.get("code") != 200:
                # 官方文档：code=999 等错误需「具体查看返回内容」，把完整返回体与排查建议一并透出。
                from push_brief import PUSHPLUS_ERROR_HINTS
                code = result.get("code")
                message = f"PushPlus 拒绝（code={code}）：{result.get('msg', '')}"
                hint = PUSHPLUS_ERROR_HINTS.get(code)
                if hint:
                    message += f"｜排查建议：{hint}"
                message += f"｜完整返回：{json.dumps(result, ensure_ascii=False)}"
                return self.send_json(HTTPStatus.BAD_GATEWAY, {"message": message})
        except HTTPError as error:
            detail = ""
            try:
                detail = error.read().decode("utf-8", "replace")
            except Exception:
                pass
            return self.send_json(HTTPStatus.BAD_GATEWAY, {
                "message": f"PushPlus 请求失败：{error}；返回内容：{detail}"
            })
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
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
