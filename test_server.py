#!/usr/bin/env python3
"""server.py 冒烟测试：在随机端口启动真实服务，验证各 API 的状态码与响应体。

在虚拟环境中运行（零第三方依赖）：

    python3 -m venv .venv
    .venv/bin/python test_server.py

回归重点：POST /api/run 及所有 API 路径都不得返回 405；
405 只可能来自静态托管（不支持 POST），而非本仓库 server.py。
"""
import json
import os
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        env = dict(os.environ)
        env.pop("PUSHPLUS_TOKEN", None)  # 确保走“未配置 token”的确定分支
        env.pop("PUSHPLUS_TOPIC", None)
        env["PORT"] = str(cls.port)
        cls.proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "server.py")],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        base = f"http://127.0.0.1:{cls.port}"
        for _ in range(50):
            try:
                urllib.request.urlopen(base + "/", timeout=1)
                break
            except Exception:
                time.sleep(0.1)
        else:
            cls.proc.kill()
            raise RuntimeError("server.py 未能启动")
        cls.base = base

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=5)

    def request(self, method, path, body=None, headers=None):
        req = urllib.request.Request(
            self.base + path,
            method=method,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers=headers or {},
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as err:
            return err.code, err.read().decode("utf-8")

    def test_index_served(self):
        status, _ = self.request("GET", "/")
        self.assertEqual(status, 200)

    def test_sources_returns_list(self):
        status, raw = self.request("GET", "/api/sources")
        self.assertEqual(status, 200)
        data = json.loads(raw)
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 1)

    def test_run_without_token_is_503_not_405(self):
        status, raw = self.request(
            "POST", "/api/run", body={},
            headers={"Content-Type": "application/json"},
        )
        # 回归点：无 token 时应是 503 且带明确提示，绝不能是 405。
        self.assertEqual(status, 503)
        self.assertIn("PUSHPLUS_TOKEN", json.loads(raw)["message"])

    def test_options_preflight_is_204(self):
        status, _ = self.request("OPTIONS", "/api/run")
        self.assertEqual(status, 204)

    def test_unknown_api_is_404(self):
        status, _ = self.request(
            "POST", "/api/not-exist", body={},
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 404)

    def test_get_run_is_404_not_405(self):
        status, _ = self.request("GET", "/api/run")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
