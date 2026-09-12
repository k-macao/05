#!/usr/bin/env python3
"""push_brief.py 推送闸门测试：大盘数据不是最新就不推（退出码 3）。

零第三方依赖，直接运行：
    python3 test_push_gate.py

思路：本地假 PushPlus（mock_pushplus.py）接收推送并写“假文件”，
把 sources 的大盘采集与 18 个新闻源全部替换为本地注入，验证：
- 大盘数据非最新 → 退出码 3，且假 PushPlus 收不到任何请求（真的没推）；
- 大盘数据最新   → 退出码 0，假文件生成且载荷正确；
- SKIP_MARKET_CHECK=1 → 跳过闸门照常推送（测试/应急通道）。
"""
import json
import os
import tempfile
import unittest

import push_brief
import sources

from test_server import free_port, start_mock


def _demo_brief():
    """18 个源全部用内置演示数据，测试不依赖外网。"""
    return {name: sources._demo_items(name)[:2] for name in sources.SOURCES}


def _injected_freshness(ok: bool):
    """注入 (market, freshness)：market 用内置快照，freshness 按需标最新/非最新。"""
    market = dict(sources._ASHARE_SNAPSHOT)
    freshness = {
        "ok": ok,
        "reason": "测试注入：" + ("大盘数据为最新" if ok else "大盘数据非最新"),
        "market_date": market["date"],
        "source": market["source"],
        "latest_kline_date": market["date"],
        "expected_date": market["date"],
        "checked_at": "2026-08-31 20:00:00",
    }
    return market, freshness


class MarketGateTest(unittest.TestCase):
    def setUp(self):
        self._orig_collect_all = sources.collect_all
        self._orig_collect_market = sources.collect_market_for_push
        self._orig_api_url = push_brief.API_URL
        sources.collect_all = _demo_brief
        self._tmp = tempfile.TemporaryDirectory()
        self.record_file = os.path.join(self._tmp.name, "pushplus_record.json")
        os.environ["PUSHPLUS_TOKEN"] = "fake-token-gate"
        os.environ.pop("SKIP_MARKET_CHECK", None)
        os.environ.pop("MARKET_FRESHNESS_FORCE", None)

    def tearDown(self):
        sources.collect_all = self._orig_collect_all
        sources.collect_market_for_push = self._orig_collect_market
        push_brief.API_URL = self._orig_api_url
        self._tmp.cleanup()
        for key in ("PUSHPLUS_TOKEN", "PUSHPLUS_API_URL", "SKIP_MARKET_CHECK",
                    "MARKET_FRESHNESS_FORCE"):
            os.environ.pop(key, None)

    def _push_once(self, fresh: bool) -> int:
        """注入大盘检查结果后执行一次 push_brief.main()，返回退出码。"""
        sources.collect_market_for_push = lambda: _injected_freshness(fresh)
        mock_port = free_port()
        mock = start_mock(mock_port, self.record_file)
        try:
            # API_URL 是模块级常量（import 时绑定），须直接改属性而非环境变量。
            push_brief.API_URL = f"http://127.0.0.1:{mock_port}/send"
            return push_brief.main()
        finally:
            mock.terminate()
            mock.wait(timeout=5)

    def test_stale_market_blocks_push(self):
        # 大盘数据非最新 → 退出码 3，且不发出任何推送请求（假文件不应生成）。
        rc = self._push_once(fresh=False)
        self.assertEqual(rc, 3)
        self.assertFalse(os.path.exists(self.record_file),
                         "大盘数据非最新时不应发出推送")

    def test_fresh_market_pushes(self):
        # 大盘数据最新 → 正常推送：假文件生成且载荷正确。
        rc = self._push_once(fresh=True)
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(self.record_file), "推送似乎没有发出")
        with open(self.record_file, encoding="utf-8") as f:
            payload = json.load(f)["payload"]
        self.assertEqual(payload["token"], "fake-token-gate")
        self.assertIn("章鱼", payload["title"])
        self.assertIn("AI 研判", payload["content"])  # 研判板块随简报一同推送
        self.assertIn("AI 板块机会", payload["content"])  # 板块机会清单随简报一同推送

    def test_skip_market_check_bypasses_gate(self):
        # SKIP_MARKET_CHECK=1（测试/应急）→ 即便非最新也照常推送。
        os.environ["SKIP_MARKET_CHECK"] = "1"
        rc = self._push_once(fresh=False)
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(self.record_file))


if __name__ == "__main__":
    unittest.main(verbosity=2)
