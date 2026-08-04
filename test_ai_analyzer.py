#!/usr/bin/env python3
"""ai_analyzer.py 的单元测试。"""
import unittest

import ai_analyzer


class AnalyzeItemTest(unittest.TestCase):
    """逐条分析接口的基础断言。"""

    def test_returns_required_keys(self):
        result = ai_analyzer.analyze_item("标普500大涨")
        for key in ("sentiment", "sectors", "market", "timeframe", "summary"):
            self.assertIn(key, result)

    def test_empty_title(self):
        result = ai_analyzer.analyze_item("")
        self.assertEqual(result["sentiment"], "中性")

    def test_bullish_detection(self):
        result = ai_analyzer.analyze_item("标普500涨幅扩大至1.5%，道指涨925点，半导体指数涨超6%")
        self.assertEqual(result["sentiment"], "利好")
        self.assertIn("半导体", result["sectors"])

    def test_bearish_detection(self):
        result = ai_analyzer.analyze_item(
            "债务逾期、25起诉讼待解、公司及实控人被立案 联创光电面临多重危机"
        )
        self.assertEqual(result["sentiment"], "利空")

    def test_market_us_stock(self):
        result = ai_analyzer.analyze_item("美股拉升，费城半导体指数涨6.2%，ARM涨超14%")
        self.assertEqual(result["market"], "美股")

    def test_market_a_stock(self):
        result = ai_analyzer.analyze_item("创业板暴涨超5.6%，算力硬件全线反攻")
        self.assertEqual(result["market"], "A股")

    def test_market_commodity(self):
        result = ai_analyzer.analyze_item("现货铂金上涨超过7%，报1745美元/盎司")
        self.assertEqual(result["market"], "商品期货")

    def test_timeframe_long(self):
        result = ai_analyzer.analyze_item(
            "L3、L4级自动驾驶强标明年7月实施 明确安全主体责任"
        )
        self.assertEqual(result["timeframe"], "长期")

    def test_timeframe_medium(self):
        result = ai_analyzer.analyze_item("诺和诺德2026年业绩前景改善，谈及GLP-1销售")
        self.assertEqual(result["timeframe"], "中期")

    def test_sector_ai(self):
        result = ai_analyzer.analyze_item(
            "Anthropic再掀算力争夺战：据称斥资100亿美元抢占数据中心资源"
        )
        self.assertIn("AI/算力", result["sectors"])


class AnalyzeItemsTest(unittest.TestCase):
    """批量分析接口测试。"""

    def test_adds_analysis_key(self):
        items = [
            {"title": "标普500大涨", "url": "https://example.com"},
            {"title": "油价重挫", "url": ""},
        ]
        result = ai_analyzer.analyze_items(items)
        self.assertEqual(len(result), 2)
        for item in result:
            self.assertIn("analysis", item)
            self.assertIn("sentiment", item["analysis"])


if __name__ == "__main__":
    unittest.main()
