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


class BuildHtmlTest(unittest.TestCase):
    def test_build_html_contains_sources_and_items(self):
        brief = {name: sources._demo_items(name)[:2] for name in sources.SOURCES}
        out = sources.build_html(brief)
        self.assertIn("覆盖 18 个数据源", out)
        self.assertIn("金十数据", out)
        self.assertIn("不构成投资建议", out)

    def test_escapes_html(self):
        out = sources.build_html({"金十数据": [{"title": "<b>x</b>", "url": ""}]})
        self.assertIn("&lt;b&gt;", out)
        self.assertNotIn("<b>x</b>", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
