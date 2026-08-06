#!/usr/bin/env python3
"""server.py 冒烟测试：在随机端口启动真实服务，验证各 API 的状态码与响应体。

在虚拟环境中运行（零第三方依赖）：

    python3 -m venv .venv
    .venv/bin/python test_server.py

回归重点：
- POST /api/run 及所有 API 路径都不得返回 405；
- 手动推送可通过 PUSHPLUS_API_URL 指向本地假服务（mock_pushplus.py），
  推送后检查记录文件（假文件）内容，验证推送请求真实发出且载荷正确。
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(port, extra_env=None):
    """启动 server.py，返回 subprocess.Popen。"""
    env = dict(os.environ)
    env.pop("PUSHPLUS_TOKEN", None)
    env.pop("PUSHPLUS_TOPIC", None)
    env.pop("PUSHPLUS_API_URL", None)
    env["PORT"] = str(port)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "server.py")],
        cwd=ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            urllib.request.urlopen(base + "/", timeout=1)
            return proc
        except Exception:
            time.sleep(0.1)
    proc.kill()
    raise RuntimeError(f"server.py 未能启动（端口 {port}）")


def start_mock(port, record_file, fail=False):
    """启动 mock_pushplus.py，返回 subprocess.Popen。"""
    env = dict(os.environ)
    env["PORT"] = str(port)
    env["RECORD_FILE"] = str(record_file)
    if fail:
        env["MOCK_FAIL"] = "1"
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "mock_pushplus.py")],
        cwd=ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(50):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
            return proc
        except Exception:
            time.sleep(0.1)
    proc.kill()
    raise RuntimeError(f"mock_pushplus.py 未能启动（端口 {port}）")


def request(base, method, path, body=None, headers=None):
    req = urllib.request.Request(
        base + path,
        method=method,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers=headers or {},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode("utf-8")


class ServerSmokeTest(unittest.TestCase):
    """无 token 场景：基础 API 行为，任何路径不得返回 405。"""

    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.proc = start_server(cls.port)
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=5)

    def test_index_served(self):
        status, _ = request(self.base, "GET", "/")
        self.assertEqual(status, 200)

    def test_sources_returns_list(self):
        status, raw = request(self.base, "GET", "/api/sources")
        self.assertEqual(status, 200)
        data = json.loads(raw)
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 1)

    def test_run_without_token_is_503_not_405(self):
        status, raw = request(
            self.base, "POST", "/api/run", body={},
            headers={"Content-Type": "application/json"},
        )
        # 回归点：无 token 时应是 503 且带明确提示，绝不能是 405。
        self.assertEqual(status, 503)
        self.assertIn("PUSHPLUS_TOKEN", json.loads(raw)["message"])

    def test_options_preflight_is_204(self):
        status, _ = request(self.base, "OPTIONS", "/api/run")
        self.assertEqual(status, 204)

    def test_unknown_api_is_404(self):
        status, _ = request(
            self.base, "POST", "/api/not-exist", body={},
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 404)

    def test_get_run_is_404_not_405(self):
        status, _ = request(self.base, "GET", "/api/run")
        self.assertEqual(status, 404)


class MockedPushTest(unittest.TestCase):
    """手动推送联调：配 token 的 server.py + 本地假 PushPlus。
    推送后检查记录文件（假文件）内容，确认推送真的发出且载荷正确。"""

    def test_push_success_writes_record_file(self):
        mock_port, srv_port = free_port(), free_port()
        with tempfile.TemporaryDirectory() as tmp:
            record_file = os.path.join(tmp, "pushplus_record.json")
            mock = start_mock(mock_port, record_file)
            srv = start_server(srv_port, {
                "PUSHPLUS_TOKEN": "fake-token-123",
                "PUSHPLUS_API_URL": f"http://127.0.0.1:{mock_port}/send",
            })
            try:
                status, raw = request(
                    f"http://127.0.0.1:{srv_port}", "POST", "/api/run", body={},
                    headers={"Content-Type": "application/json"},
                )
                # 手动推送成功：server.py 返回 200 与成功提示。
                self.assertEqual(status, 200)
                self.assertIn("推送至 PushPlus", json.loads(raw)["message"])

                # 假文件必须存在且有内容。
                self.assertTrue(os.path.exists(record_file), "假文件未生成，推送似乎没有发出")
                record = json.loads(PathRead(record_file))
                payload = record["payload"]
                self.assertEqual(record["method"], "POST")
                self.assertEqual(record["path"], "/send")
                self.assertEqual(payload["token"], "fake-token-123")
                self.assertEqual(payload["template"], "html")
                self.assertIn("章鱼", payload["title"])
                # 推送内容为真实抓取的 18 个数据源 HTML 简报（网络不可用时回退演示数据）。
                self.assertIn("章鱼", payload["content"])
                self.assertIn("数据源", payload["content"])
            finally:
                srv.terminate(); srv.wait(timeout=5)
                mock.terminate(); mock.wait(timeout=5)

    def test_push_rejected_returns_502(self):
        mock_port, srv_port = free_port(), free_port()
        with tempfile.TemporaryDirectory() as tmp:
            record_file = os.path.join(tmp, "pushplus_record.json")
            mock = start_mock(mock_port, record_file, fail=True)
            srv = start_server(srv_port, {
                "PUSHPLUS_TOKEN": "fake-token-123",
                "PUSHPLUS_API_URL": f"http://127.0.0.1:{mock_port}/send",
            })
            try:
                status, raw = request(
                    f"http://127.0.0.1:{srv_port}", "POST", "/api/run", body={},
                    headers={"Content-Type": "application/json"},
                )
                # PushPlus 拒绝（业务码非 200）→ server.py 应返回 502 并透出原因。
                self.assertEqual(status, 502)
                self.assertIn("token invalid", json.loads(raw)["message"])
            finally:
                srv.terminate(); srv.wait(timeout=5)
                mock.terminate(); mock.wait(timeout=5)


def PathRead(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


if __name__ == "__main__":
    unittest.main(verbosity=2)
