#!/usr/bin/env python3
"""sources.py 单元测试：链接解析、源定义、兜底数据、HTML 渲染。

零第三方依赖，直接运行：
    python3 test_sources.py
"""
import unittest

import sources


# 模拟 rebang.vip 聚合页的服务端渲染结构：<a href> 指回源头站 + 内部导航噪音。
_SAMPLE_HTML = """
<html><body>
<nav><a href="https://www.rebang.vip/">首页</a>
<a href="https://www.rebang.vip/weibo/hot-search">微博热搜</a></nav>
<section>
<a href="https://www.cls.cn/detail/2445436">19分钟前<br/>L3、L4级自动驾驶“强标”明年7月实施</a>
<a href="https://www.cls.cn/detail/2445625">25分钟前 央行将开展5000亿元买断式逆回购</a>
<a href="https://www.cls.cn/detail/2445058">1小时前 日元又成了全世界的问题</a>
</section>
</body></html>
"""


class LinkCollectorTest(unittest.TestCase):
    def test_collects_anchors(self):
        parser = sources.LinkCollector()
        parser.feed(_SAMPLE_HTML)
        hrefs = [href for href, _ in parser.links]
        self.assertIn("https://www.cls.cn/detail/2445436", hrefs)
        self.assertIn("https://www.rebang.vip/weibo/hot-search", hrefs)

    def test_clean_title_strips_time_prefix(self):
        self.assertEqual(sources._clean_title("19分钟前 L3、L4级自动驾驶“强标”"), "L3、L4级自动驾驶“强标”")
        self.assertEqual(sources._clean_title("1小时前 标题"), "标题")
        self.assertEqual(sources._clean_title("无前缀标题"), "无前缀标题")


class ParseChannelTest(unittest.TestCase):
    def test_parse_channel_filters_by_origin(self):
        # 用本地样本验证：只保留指向 cls.cn 的条目，忽略导航噪音，且去重截断。
        parser = sources.LinkCollector()
        parser.feed(_SAMPLE_HTML)
        out = sources._filter_items(parser.links, origin="cls.cn", limit=10)
        self.assertEqual(len(out), 3)
        self.assertTrue(all("cls.cn" in it["url"] for it in out))
        self.assertNotIn("微博热搜", [it["title"] for it in out])
        # 截断生效
        self.assertEqual(len(sources._filter_items(parser.links, "cls.cn", limit=2)), 2)


class SourceDefinitionTest(unittest.TestCase):
    def test_eighteen_sources(self):
        self.assertEqual(len(sources.SOURCES), 18)
        self.assertEqual(len(sources.SOURCE_META), 18)
        names = [m["name"] for m in sources.SOURCE_META]
        self.assertEqual(names, sources.SOURCES)

    def test_every_source_has_origin_or_collector(self):
        for meta in sources.SOURCE_META:
            # 原有的 12 个源有 origin 和 channel，新增的 6 个源有 collector
            has_channel = "channel" in meta and "origin" in meta
            has_collector = "collector" in meta
            self.assertTrue(has_channel or has_collector, f"{meta['name']} 缺少 channel 或 collector")

    def test_demo_fallback(self):
        for name in sources.SOURCES:
            items = sources._demo_items(name)
            self.assertGreaterEqual(len(items), 1, name)
            self.assertTrue(items[0]["title"])

    def test_collect_one_falls_back_offline(self):
        # 无外网环境（如 CI 沙箱）也能返回兜底数据。
        items = sources.collect_one("金十数据")
        self.assertGreaterEqual(len(items), 1)
        # 新增的源也应该有兜底数据
        items = sources.collect_one("知乎热榜")
        self.assertGreaterEqual(len(items), 1)


class AnalyzeBriefTest(unittest.TestCase):
    def _brief(self, titles, sources=("金十数据",)):
        return {name: [{"title": t, "url": ""} for t in titles] for name in sources}

    def test_returns_expected_fields(self):
        ana = sources.analyze_brief(self._brief(["现货铂金上涨超过7%", "标普500涨幅扩大至1.5%"]))
        for key in ("headline", "bias", "bull", "bear", "sectors", "top_themes"):
            self.assertIn(key, ana)
        self.assertEqual(ana["bull"] + ana["bear"], 100)
        self.assertIn(ana["bias"], ("偏多", "偏空", "中性"))

    def test_bullish_input_is_pianduo(self):
        ana = sources.analyze_brief(self._brief(["标普500涨幅扩大至1.5%", "现货铂金上涨超过7%", "云业务积压订单暴增150%"]))
        self.assertEqual(ana["bias"], "偏多")
        self.assertGreater(ana["bull"], ana["bear"])

    def test_bearish_input_is_piankong(self):
        ana = sources.analyze_brief(self._brief(["债务逾期、25起诉讼待解", "美股暴跌风险警示", "公司被立案面临多重危机"]))
        self.assertEqual(ana["bias"], "偏空")
        self.assertLess(ana["bull"], ana["bear"])

    def test_theme_detection(self):
        ana = sources.analyze_brief(self._brief(["OpenAI 发布 GPT-5 技术预览版", "Anthropic 数据中心大额投资"]))
        tags = [t[0] for t in ana["top_themes"]]
        self.assertIn("AI 算力", tags)

    def test_headline_references_top_theme(self):
        ana = sources.analyze_brief(self._brief(["OpenAI 发布 GPT-5 技术预览版", "AI 编程助手效率对比评测"]))
        self.assertTrue(any(tag in ana["headline"] for tag in ana["sectors"]))

    def test_empty_brief_is_neutral(self):
        ana = sources.analyze_brief({})
        self.assertEqual(ana["bias"], "中性")
        self.assertEqual((ana["bull"], ana["bear"]), (50, 50))

    def test_demo_brief_has_nonempty_summary(self):
        brief = {name: sources._demo_items(name) for name in sources.SOURCES}
        ana = sources.analyze_brief(brief)
        self.assertTrue(ana["headline"])
        self.assertTrue(ana["sectors"])

    def test_four_viewpoints_present(self):
        # 开篇四个观点：市场情绪 / 多空博弈概率 / 利好·利差板块 / 资金流向分析。
        ana = sources.analyze_brief(self._brief(["标普500涨幅扩大至1.5%", "现货铂金上涨超过7%"]))
        self.assertEqual(
            [p["label"] for p in ana["points"]],
            ["市场情绪", "多空博弈概率", "利好 / 利差板块", "资金流向分析"],
        )
        self.assertTrue(all(p["text"] for p in ana["points"]))
        for key in ("sectors_up", "sectors_down", "flow"):
            self.assertIn(key, ana)

    def test_battle_point_has_percent_and_sample_size(self):
        ana = sources.analyze_brief(self._brief(["标普500涨幅扩大至1.5%", "美股暴跌风险警示"]))
        battle = next(p["text"] for p in ana["points"] if p["key"] == "battle")
        self.assertIn("多方", battle)
        self.assertIn("%", battle)
        self.assertIn("多空信号", battle)

    def test_bullish_and_bearish_sectors_split(self):
        titles = [
            "AI 算力投资创纪录，数据中心扩产超预期",
            "光模块订单暴增，光通信景气度回升",
            "地产股债务逾期风险警示，房价承压下跌",
        ]
        ana = sources.analyze_brief(self._brief(titles))
        self.assertIn("AI 算力", ana["sectors_up"])
        self.assertNotIn("地产", ana["sectors_up"])
        self.assertIn("地产", ana["sectors_down"])
        self.assertIn("地产", ana["flow"])
        self.assertIn("回避", ana["flow"])

    def test_empty_brief_points_are_honest(self):
        ana = sources.analyze_brief({})
        self.assertEqual(ana["sectors_up"], [])
        self.assertEqual(ana["sectors_down"], [])
        battle = next(p["text"] for p in ana["points"] if p["key"] == "battle")
        self.assertIn("暂无", battle)


class BuildHtmlTest(unittest.TestCase):
    def test_build_html_contains_sources_and_items(self):
        brief = {name: sources._demo_items(name)[:2] for name in sources.SOURCES}
        out = sources.build_html(brief)
        self.assertIn("覆盖 18 个数据源", out)
        self.assertIn("金十数据", out)
        self.assertIn("不构成投资建议", out)

    def test_build_html_renders_four_viewpoints(self):
        brief = {name: sources._demo_items(name)[:2] for name in sources.SOURCES}
        out = sources.build_html(brief)
        for label in ("市场情绪", "多空博弈概率", "利好 / 利差板块", "资金流向分析"):
            self.assertIn(label, out)

    def test_build_html_empty_brief_renders_points_fallback(self):
        out = sources.build_html({})
        self.assertIn("暂无可统计的多空信号", out)
        self.assertIn("资金流向分析", out)

    def test_escapes_html(self):
        out = sources.build_html({"金十数据": [{"title": "<b>x</b>", "url": ""}]})
        self.assertIn("&lt;b&gt;", out)
        self.assertNotIn("<b>x</b>", out)


class AshareReviewTest(unittest.TestCase):
    """前日 A 股六维度复盘：内容策略、数据解析、复盘日选取、离线兜底与 HTML 渲染。"""

    CANDLE = ("2026-08-27,3911.89,3956.57,3958.03,3909.31,516777549,"
              "1010226573954.60,1.25,1.13,44.05,1.07")

    def test_parse_candle(self):
        candle = sources._parse_ashare_candle(self.CANDLE)
        self.assertEqual(candle["date"], "2026-08-27")
        self.assertEqual(candle["close"], 3956.57)
        self.assertEqual(candle["pct"], 1.13)
        self.assertEqual(candle["change"], 44.05)
        self.assertEqual(candle["amount"], 1010226573954.60)
        self.assertIsNone(sources._parse_ashare_candle(""))

    def test_pick_review_date_is_day_before_yesterday(self):
        # 今天 2026-08-29（周六）→「前天」复盘日 = 2026-08-27（最近交易日）。
        klines = {
            "上证指数": {"2026-08-27": {}, "2026-08-28": {}},
            "深证成指": {"2026-08-27": {}},
        }
        from datetime import date
        self.assertEqual(sources._pick_review_date(klines, date(2026, 8, 29)), "2026-08-27")
        # 周一 2026-08-31：前天是周六无交易，回溯到 2026-08-28（周五）。
        self.assertEqual(sources._pick_review_date(klines, date(2026, 8, 31)), "2026-08-28")

    def test_get_fallback_review_date(self):
        from datetime import date
        # 周日 2026-08-30 → 前天周五 2026-08-28
        self.assertEqual(sources._get_fallback_review_date(date(2026, 8, 30)), "2026-08-28")
        # 周一 2026-08-31 → 周六无交易，向前回溯到周五 2026-08-28
        self.assertEqual(sources._get_fallback_review_date(date(2026, 8, 31)), "2026-08-28")
        # 周六 2026-08-29 → 前天周四 2026-08-27
        self.assertEqual(sources._get_fallback_review_date(date(2026, 8, 29)), "2026-08-27")

    def test_analyze_ashare_has_six_dimensions(self):
        review = sources.analyze_ashare(market=sources._ASHARE_SNAPSHOT)
        self.assertEqual(review["date"], sources._ASHARE_SNAPSHOT["date"])
        self.assertEqual(
            [p["label"] for p in review["points"]],
            ["三大指数", "两市成交额", "涨跌家数与涨跌停",
             "领涨 / 领跌板块", "主力资金与北向资金", "后市观点与策略"],
        )
        self.assertTrue(all(p["text"] for p in review["points"]))
        self.assertIn(review["bias"], ("偏多", "偏空", "中性"))

    def test_analyze_ashare_snapshot_content(self):
        review = sources.analyze_ashare(market=sources._ASHARE_SNAPSHOT)
        texts = {p["label"]: p["text"] for p in review["points"]}
        # ① 指数：四大指数收盘与涨幅
        self.assertIn("3956.57", texts["三大指数"])
        self.assertIn("科创50", texts["三大指数"])
        # ② 成交额：2.13 万亿、放量 3172 亿（与新浪/每经收评交叉核对口径）
        self.assertIn("2.13 万亿", texts["两市成交额"])
        self.assertIn("3,172 亿", texts["两市成交额"])
        # ③ 涨跌家数与涨跌停：涨停 77 / 跌停 3 / 封板率 82%
        self.assertIn("涨停 77 家", texts["涨跌家数与涨跌停"])
        self.assertIn("跌停 3 家", texts["涨跌家数与涨跌停"])
        # ④ 领涨/领跌板块
        self.assertIn("算力硬件", texts["领涨 / 领跌板块"])
        self.assertIn("银行", texts["领涨 / 领跌板块"])
        # ⑤ 北向口径说明
        self.assertIn("北向资金", texts["主力资金与北向资金"])
        # ⑥ 后市观点与策略
        self.assertIn("AI 研判", texts["后市观点与策略"])
        self.assertIn("浙商证券", texts["后市观点与策略"])

    def test_snapshot_headline_mentions_leaders(self):
        review = sources.analyze_ashare(market=sources._ASHARE_SNAPSHOT)
        self.assertIn("算力硬件", review["headline"])
        self.assertIn("存储芯片", review["headline"])

    def test_get_ashare_market_falls_back_offline(self):
        # 无外网环境（如 CI 沙箱）：网络层抛错时必须回退内置真实快照（且复盘日期基于当前日期动态推导），绝不空转。
        original = sources.urlopen

        def _offline(*args, **kwargs):
            raise OSError("network unreachable")

        sources.urlopen = _offline
        try:
            market = sources.get_ashare_market()
        finally:
            sources.urlopen = original
        self.assertEqual(market["date"], sources._get_fallback_review_date())
        self.assertEqual(market["source"], "snapshot")

    def test_build_html_renders_ashare_review_card(self):
        brief = {name: sources._demo_items(name)[:2] for name in sources.SOURCES}
        review = sources.analyze_ashare(market=sources._ASHARE_SNAPSHOT)
        out = sources.build_html(brief, review=review)
        self.assertIn("AI 复盘 · 前日 A 股", out)
        self.assertIn(sources._ASHARE_SNAPSHOT["date"], out)
        for label in ("三大指数", "两市成交额", "涨跌家数与涨跌停",
                      "领涨 / 领跌板块", "主力资金与北向资金", "后市观点与策略"):
            self.assertIn(label, out)
        self.assertIn("偏多", out)

    def test_review_sector_names_are_escaped(self):
        market = dict(sources._ASHARE_SNAPSHOT)
        market["leaders"] = [{"name": "<算力>", "note": "x"}]
        market["laggards"] = [{"name": "银行", "note": "x"}]
        brief = {"金十数据": [{"title": "x", "url": ""}]}
        out = sources.build_html(brief, review=sources.analyze_ashare(market=market))
        self.assertIn("&lt;算力&gt;", out)
        self.assertNotIn("<算力>", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
