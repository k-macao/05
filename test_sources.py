#!/usr/bin/env python3
"""sources.py 单元测试：链接解析、源定义、兜底数据、HTML 渲染。

零第三方依赖，直接运行：
    python3 test_sources.py
"""
import os
import unittest
from datetime import date

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
    def test_forty_eight_sources_in_five_sections(self):
        # 12 财经快讯 + 6 热搜热点 + 14 政策发布 · 官方信息源 + 12 全球政经媒体 + 4 公民科技 · 政治透明度。
        self.assertEqual(len(sources.SOURCES), 48)
        self.assertEqual(len(sources.SOURCE_META), 48)
        self.assertEqual(len(set(sources.SOURCES)), 48, "数据源名称必须唯一")
        names = [m["name"] for m in sources.SOURCE_META]
        self.assertEqual(names, sources.SOURCES)
        counts = {sec["key"]: sec["count"] for sec in sources.section_catalog()}
        self.assertEqual(counts, {"finance": 12, "trending": 6, "policy": 14, "world": 12, "civic": 4})

    def test_every_source_has_a_fetch_method(self):
        for meta in sources.SOURCE_META:
            # 四选一：rebang 聚合通道（origin+channel）/ 自定义收集器 / RSS·Atom 订阅 / 列表页+正则。
            has_channel = "channel" in meta and "origin" in meta
            has_collector = "collector" in meta and meta["collector"] in sources._COLLECTORS
            has_feed = "feed" in meta
            has_page = "page" in meta and "pattern" in meta
            self.assertTrue(has_channel or has_collector or has_feed or has_page,
                            f"{meta['name']} 缺少抓取方式")
            self.assertIn(meta.get("section"), sources.SECTION_KEYS, f"{meta['name']} 板块归属无效")

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


_SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Bloomberg Politics</title>
<item><title><![CDATA[US Reaches Greenland Deal to End Row That Threatened NATO]]></title>
<link>https://www.bloomberg.com/news/articles/2026-09-19/greenland</link></item>
<item><title>China Slams US Law Tightening Sanctions on Russia and Iran</title>
<link>https://www.bloomberg.com/news/articles/2026-09-19/sanctions</link></item>
<item><title>China Slams US Law Tightening Sanctions on Russia and Iran</title>
<link>https://www.bloomberg.com/news/articles/2026-09-19/sanctions-dup</link></item>
<item><title>German general Breuer elected to head top NATO military body - Reuters</title>
<link>https://news.google.com/rss/articles/abc</link></item>
</channel></rss>"""

_SAMPLE_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>HM Treasury - Activity on GOV.UK</title>
<entry><title>Chancellor sets date for Autumn Budget 2026</title>
<link rel="alternate" type="text/html" href="https://www.gov.uk/government/news/autumn-budget-2026"/></entry>
<entry><title>Pensions investment reform: consultation response</title>
<link rel="self" href="https://www.gov.uk/self"/>
<link rel="alternate" href="https://www.gov.uk/government/consultations/pensions"/></entry>
</feed>"""

# 模拟 gov.cn「最新政策」列表页：相对链接 + 同一条目上的短锚文本 + 栏目导航噪音。
_SAMPLE_GOV_HTML = """
<html><body>
<a href="https://www.gov.cn/zhengce/">最新政策</a>
<ul>
<li><a href="./202609/content_7081441.htm">国务院办公厅转发文化和旅游部等部门《关于促进房车消费的若干措施》的通知</a>
    <a href="./202609/content_7081441.htm">解读</a></li>
<li><a href="/zhengce/content/202609/content_7081356.htm">国务院办公厅关于进一步加强烟花爆竹全链条安全监管的意见</a></li>
<li><a href="https://www.gov.cn/zhengce/jiedu/202609/content_7081473.htm">解读：国务院常务会议部署实施医疗康复护理扩容提升工程</a></li>
<li><a href="https://www.gov.cn/xinwen/2026/other.htm">不是政策条目的其他链接</a></li>
</ul>
</body></html>
"""


class SectionTest(unittest.TestCase):
    """五大板块：板块目录、按板块抓取、通用 RSS·Atom / 列表页抓取器、公民科技 JSON 解析、快讯分组渲染。"""

    def test_section_catalog(self):
        catalog = sources.section_catalog()
        self.assertEqual([sec["key"] for sec in catalog], ["finance", "trending", "policy", "world", "civic"])
        self.assertEqual(sum(sec["count"] for sec in catalog), len(sources.SOURCES))
        labels = [sec["label"] for sec in catalog]
        # 板块名不能与任何数据源名相同，否则「全网快讯」分组标题会暴露来源。
        for label in labels:
            self.assertNotIn(label, sources.SOURCES)
        self.assertEqual(sources.section_of("国务院 最新政策"), "policy")
        self.assertEqual(sources.section_of("Bloomberg 政治"), "world")
        self.assertEqual(sources.section_of("g0v 立法院議案"), "civic")
        self.assertEqual(sources.section_of("金十数据"), "finance")
        self.assertEqual(sources.section_of("未登记的源"), "finance")

    def test_collect_section_falls_back_offline(self):
        # 无外网环境按板块抓取也能整板块回退演示数据，且顺序与 SOURCE_META 一致。
        out = sources.collect_section("policy")
        self.assertEqual(list(out), sources.sources_in_section("policy"))
        self.assertTrue(all(len(items) >= 1 for items in out.values()))
        self.assertEqual(sources.collect_section("no-such-section"), {})

    def test_collect_all_keeps_source_order_when_parallel(self):
        os.environ["BRIEF_FETCH_WORKERS"] = "6"
        try:
            self.assertEqual(sources.fetch_workers(), 6)
            out = sources.collect_all()
        finally:
            os.environ.pop("BRIEF_FETCH_WORKERS", None)
        self.assertEqual(list(out), sources.SOURCES)
        self.assertTrue(all(len(items) >= 1 for items in out.values()))
        self.assertEqual(sources.fetch_workers(), sources.FETCH_WORKERS_DEFAULT)

    def test_parse_feed_rss_dedupes_and_strips_suffix(self):
        items = sources._parse_feed(_SAMPLE_RSS, limit=10, strip_suffix=" - Reuters")
        titles = [it["title"] for it in items]
        self.assertEqual(titles, [
            "US Reaches Greenland Deal to End Row That Threatened NATO",
            "China Slams US Law Tightening Sanctions on Russia and Iran",
            "German general Breuer elected to head top NATO military body",
        ])
        self.assertEqual(items[0]["url"], "https://www.bloomberg.com/news/articles/2026-09-19/greenland")
        self.assertEqual(len(sources._parse_feed(_SAMPLE_RSS, limit=1)), 1)
        # bytes 入参（真实抓取按声明 encoding 解码）同样可用。
        self.assertEqual(len(sources._parse_feed(_SAMPLE_RSS.encode("utf-8"), limit=10)), 3)

    def test_parse_feed_atom_prefers_alternate_link(self):
        items = sources._parse_feed(_SAMPLE_ATOM, limit=10)
        self.assertEqual([it["title"] for it in items], [
            "Chancellor sets date for Autumn Budget 2026",
            "Pensions investment reform: consultation response",
        ])
        self.assertEqual(items[0]["url"], "https://www.gov.uk/government/news/autumn-budget-2026")
        self.assertEqual(items[1]["url"], "https://www.gov.uk/government/consultations/pensions")

    def test_parse_feed_rejects_garbage(self):
        with self.assertRaises(sources.ET.ParseError):
            sources._parse_feed("<html><body>not a feed", limit=5)
        # collect_one 会把解析失败吞掉并回退演示数据。
        self.assertTrue(issubclass(sources.ET.ParseError, sources._FETCH_ERRORS))

    def test_filter_page_links_resolves_relative_and_skips_nav(self):
        parser = sources.LinkCollector()
        parser.feed(_SAMPLE_GOV_HTML)
        items = sources._filter_page_links(parser.links, sources._GOVCN_PATTERN,
                                           "https://www.gov.cn/zhengce/zuixin/", limit=10)
        urls = [it["url"] for it in items]
        self.assertEqual(urls, [
            "https://www.gov.cn/zhengce/zuixin/202609/content_7081441.htm",
            "https://www.gov.cn/zhengce/content/202609/content_7081356.htm",
            "https://www.gov.cn/zhengce/jiedu/202609/content_7081473.htm",
        ])
        titles = [it["title"] for it in items]
        self.assertNotIn("解读", titles)          # 短锚文本不当标题
        self.assertNotIn("最新政策", titles)      # 栏目导航不匹配条目正则
        self.assertEqual(len(sources._filter_page_links(parser.links, sources._GOVCN_PATTERN,
                                                        "https://www.gov.cn/zhengce/zuixin/", limit=2)), 2)

    def test_ministry_patterns_match_real_link_shapes(self):
        meta = {m["name"]: m for m in sources.SOURCE_META}
        cases = {
            "发改委 政策发布": "https://www.ndrc.gov.cn/xxgk/zcfb/tz/202609/t20260917_1407686.html",
            "财政部 政策发布": "http://gks.mof.gov.cn/guizhangzhidu/202609/t20260911_3997286.htm",
            "商务部 政策发布": "https://www.mofcom.gov.cn/zwgk/zcfb/art/2026/art_98f578b88d3f47538d7b516745faf230.html",
            "证监会 新闻发布": "https://www.csrc.gov.cn/csrc/c100028/c7659506/content.shtml",
        }
        import re
        for name, url in cases.items():
            self.assertTrue(re.search(meta[name]["pattern"], url), name)
        # 解读 / 旧栏目链接不算条目。
        self.assertFalse(re.search(meta["发改委 政策发布"]["pattern"], "https://www.ndrc.gov.cn/xxgk/jd/jd/202609/t20260917_1.html"))
        self.assertFalse(re.search(meta["证监会 新闻发布"]["pattern"], "https://www.csrc.gov.cn/csrc/c100029/c7473708/content.shtml"))

    def test_decode_honours_meta_charset(self):
        gbk_page = '<html><head><meta charset="gb2312"></head><body>财政部 政策发布</body></html>'.encode("gb18030")
        self.assertIn("财政部 政策发布", sources._decode(gbk_page))
        self.assertIn("财政部", sources._decode("财政部".encode("utf-8"), "utf-8"))
        self.assertIn("财政部", sources._decode("财政部".encode("utf-8"), "no-such-charset"))

    def test_format_ly_bills(self):
        data = {"bills": [
            {"議案名稱": "「食品安全衛生管理法部分條文修正草案」，請審議案。", "議案狀態": "排入院會",
             "提案單位/提案委員": "本院委員陳菁徽等17人", "url": "https://ppg.ly.gov.tw/ppg/bills/202110231310000/details"},
            {"議案名稱": "", "議案狀態": "x"},
            {"議案名稱": "Ａ" * 120, "url": ""},
        ]}
        items = sources._format_ly_bills(data, limit=10)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["title"], "〔排入院會〕「食品安全衛生管理法部分條文修正草案」，請審議案。（本院委員陳菁徽等17人）")
        self.assertEqual(items[0]["url"], "https://ppg.ly.gov.tw/ppg/bills/202110231310000/details")
        self.assertTrue(items[1]["title"].endswith("…"))
        self.assertEqual(sources._format_ly_bills({}, limit=5), [])

    def test_format_equitystack_promises_sorted_by_latest_action(self):
        data = {"items": [
            {"slug": "old", "title": "Older promise", "status": "Partial", "topic": "Education",
             "president": "Donald J. Trump", "promise_date": "2025-01-20", "latest_action_date": "2025-04-23"},
            {"slug": "new", "title": "Newer promise", "status": "Failed", "topic": "Courts",
             "president": "Donald J. Trump", "promise_date": "2026-04-29", "latest_action_date": "2026-04-29"},
            {"slug": "none", "title": ""},
        ]}
        items = sources._format_equitystack_promises(data, limit=10)
        self.assertEqual([it["url"] for it in items],
                         ["https://equitystack.org/promises/new", "https://equitystack.org/promises/old"])
        self.assertEqual(items[0]["title"], "[Failed] Newer promise（Courts · Donald J. Trump）")
        # 裸数组响应也兼容。
        self.assertEqual(len(sources._format_equitystack_promises(data["items"], limit=1)), 1)

    def test_format_equitystack_bills(self):
        data = [{"title": "Reparations study commission", "status": "Idea", "tracked_bills": [
            {"bill_number": "H.R. 40", "title": "Commission to Study and Develop Reparation Proposals for African Americans Act",
             "status": "In Committee", "latest_action": "Referred to the House Committee on the Judiciary.",
             "url": "https://www.congress.gov/bill/118th-congress/hr-bill/40"}]},
            {"title": "Idea without tracked bill", "status": "Idea", "tracked_bills": []}]
        items = sources._format_equitystack_bills(data, limit=10)
        self.assertEqual(items[0]["title"],
                         "H.R. 40｜Commission to Study and Develop Reparation Proposals for African Americans Act"
                         "（In Committee · Referred to the House Committee on the Judiciary.）")
        self.assertEqual(items[0]["url"], "https://www.congress.gov/bill/118th-congress/hr-bill/40")
        self.assertEqual(items[1]["title"], "Idea without tracked bill（Idea）")

    def test_english_titles_feed_theme_policy_and_direction(self):
        # 英文政策 / 媒体标题：主题按单词边界归类（AI 不误命中 SAID / AIR），多空与鹰鸽同样计票。
        ana = sources.analyze_brief({
            "Bloomberg 政治": [
                {"title": "China Slams US Law Tightening Sanctions on Russia and Iran", "url": ""},
                {"title": "Saudi Arabia Issues Rare Air-Raid Alerts for Riyadh", "url": ""},
            ],
            "美联储 新闻稿": [{"title": "Federal Reserve issues FOMC statement", "url": ""}],
            "Financial Times": [{"title": "Gold surges to record high as dollar slides", "url": ""}],
        })
        tags = dict((t[0], t) for t in ana["top_themes"])
        self.assertIn("地缘", tags)
        self.assertIn("美联储", tags)
        self.assertIn("贵金属", tags)
        self.assertNotIn("AI 算力", tags)
        self.assertIn("贵金属", ana["sectors_up"])
        self.assertGreaterEqual(ana["signals"], 2)
        policy = ana["policy"]
        bucket_tags = {b["tag"] for b in policy["buckets"]}
        self.assertIn("地缘与贸易政策", bucket_tags)
        self.assertIn("货币政策 · 美联储", bucket_tags)
        self.assertEqual(policy["stance"], "偏鹰")
        # 板块口径：三条来自两个板块。
        secs = {s["key"]: s for s in ana["sections"]}
        self.assertEqual(secs["world"]["items"], 3)
        self.assertEqual(secs["world"]["sources"], 2)
        self.assertEqual(secs["policy"]["items"], 1)

    def test_demo_policy_sources_hit_policy_buckets(self):
        brief = {name: sources._demo_items(name) for name in sources.sources_in_section("policy")}
        p = sources.analyze_policy(brief)
        self.assertGreaterEqual(p["sources_hit"], 10)
        self.assertGreaterEqual(p["mentions"], 30)

    def test_news_card_groups_by_section(self):
        brief = {
            "金十数据": [{"title": "金十快讯标题一", "url": ""}],
            "国务院 最新政策": [{"title": "国务院办公厅关于加强中小企业回款难问题治理的通知", "url": ""}],
            "Bloomberg 政治": [{"title": "US Reaches Greenland Deal to End Row That Threatened NATO", "url": ""}],
            "外部投稿": [{"title": "调用方额外传入的一条标题", "url": ""}],
        }
        out = sources.build_html(brief, **PolicySectionTest._kanpan())
        card = out[out.index("全网快讯"):]
        for label in ("财经快讯", "政策发布 · 官方信息源", "全球政经媒体", "其他"):
            self.assertIn(label, card)
        self.assertNotIn("热搜热点", card)     # 没有内容的板块不出现
        self.assertIn("4 个板块", card)
        self.assertIn("共 4 条", card)
        # 编号全表连续，来源名不出现。
        self.assertLess(card.index("金十快讯标题一"), card.index("国务院办公厅关于"))
        self.assertLess(card.index("国务院办公厅关于"), card.index("Greenland"))
        self.assertIn(">04</td>", card)
        for name in ("金十数据", "国务院 最新政策", "Bloomberg 政治", "外部投稿"):
            self.assertNotIn(name, card)


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


class SectorOpportunityTest(unittest.TestCase):
    """「AI 板块机会」板块：机会方向（净多头 Top 4）/ 承压方向（净空头 Top 2）+ 支撑证据。"""

    def _brief(self, titles, sources=("金十数据",)):
        return {name: [{"title": t, "url": f"https://example.com/{i}"} for i, t in enumerate(titles)]
                for name in sources}

    def test_opportunity_fields_and_counts(self):
        ana = sources.analyze_brief(self._brief([
            "贵金属黄金价格暴涨创新高",
            "地产股债务逾期风险警示，房价承压下跌",
        ]))
        opp = ana["opportunity_sectors"]
        self.assertEqual(len(opp), 1)
        self.assertEqual(opp[0]["tag"], "贵金属")
        self.assertEqual(opp[0]["up"], 1)
        self.assertEqual(opp[0]["down"], 0)
        self.assertEqual(opp[0]["net"], 1)
        self.assertEqual(opp[0]["mentions"], 1)
        self.assertEqual(opp[0]["sources"], 1)
        self.assertEqual(len(opp[0]["evidence"]), 1)
        self.assertEqual(opp[0]["evidence"][0]["source"], "金十数据")
        self.assertTrue(opp[0]["evidence"][0]["title"])

    def test_opportunity_ranking_and_top4_limit(self):
        # 净多信号：贵金属 3、AI 算力 2、其余各 1 → 按净信号强度排序，且只取 Top 4。
        titles = [
            "黄金价格暴涨创新高",
            "白银大幅上涨，贵金属反弹",
            "稀土矿产出口利好，价格回升",
            "AI 算力投资创新高，数据中心扩产超预期",
            "人工智能大模型订单暴增",
            "光模块订单暴增，光通信景气度回升",
            "半导体设备股大涨，芯片扩产加速",
            "央行宣布降息，美元流动性暴增",
            "医药医疗股反弹，临床数据超预期",
        ]
        ana = sources.analyze_brief(self._brief(titles))
        tags = [e["tag"] for e in ana["opportunity_sectors"]]
        self.assertEqual(len(tags), 4)
        self.assertEqual(tags[0], "贵金属")
        self.assertEqual(tags[1], "AI 算力")
        self.assertNotIn("美联储", tags)  # 净信号较弱的主题被 Top 4 截断
        # 前 3 名必须与「利好 / 利差板块」观点的利好板块一致（同一套排序）。
        self.assertEqual(tags[:3], ana["sectors_up"])

    def test_pressure_ranking_and_top2_limit(self):
        # 净空信号：地产 2、地缘 1、消费 1 → 承压方向只取 Top 2。
        titles = [
            "地产股债务逾期，房价下跌承压",
            "楼市房企风险警示，股价暴跌",
            "伊朗海峡危机风险警示",
            "消费疲软，零售额下跌",
        ]
        ana = sources.analyze_brief(self._brief(titles))
        tags = [e["tag"] for e in ana["pressure_sectors"]]
        self.assertEqual(tags, ["地产", "地缘"])
        self.assertEqual(ana["pressure_sectors"][0]["net"], -2)
        self.assertNotIn("消费", tags)
        self.assertEqual(tags[:2], ana["sectors_down"])

    def test_evidence_prefers_matching_direction(self):
        titles = [
            "AI 大模型扩产，算力投资暴增",
            "人工智能数据中心订单超预期",
            "AI 概念股暴跌，算力泡沫争议",
        ]
        ana = sources.analyze_brief(self._brief(titles))
        opp = ana["opportunity_sectors"][0]
        self.assertEqual(opp["tag"], "AI 算力")
        self.assertEqual(opp["up"], 2)
        self.assertEqual(opp["down"], 1)
        self.assertEqual([ev["title"] for ev in opp["evidence"]],
                         [titles[0], titles[1], titles[2]])  # 多头证据在前

    def test_evidence_keeps_cross_source_corroboration(self):
        # 同一标题被多个数据源命中（跨源佐证）：证据保留两条，便于展示多源共振。
        ana = sources.analyze_brief(self._brief(
            ["黄金价格暴涨创新高"], sources=("金十数据", "财联社 电报")))
        opp = ana["opportunity_sectors"][0]
        self.assertEqual(opp["sources"], 2)
        self.assertEqual(len(opp["evidence"]), 2)
        self.assertEqual({ev["source"] for ev in opp["evidence"]}, {"金十数据", "财联社 电报"})

    def test_signals_sample_size(self):
        ana = sources.analyze_brief(self._brief([
            "黄金价格暴涨创新高",
            "地产股债务逾期风险警示，房价下跌",
            "今天天气不错",  # 无方向信号，不计入样本
        ]))
        self.assertEqual(ana["signals"], 2)

    def test_empty_brief_has_no_opportunities(self):
        ana = sources.analyze_brief({})
        self.assertEqual(ana["opportunity_sectors"], [])
        self.assertEqual(ana["pressure_sectors"], [])
        self.assertEqual(ana["signals"], 0)



class PolicySectionTest(unittest.TestCase):
    """「AI 政策分析」板块：政策维度热度 + 多空方向 + 鹰鸽取向（含否定翻转）。"""

    def _brief(self, titles, src=("金十数据",)):
        return {name: [{"title": t, "url": f"https://example.com/{i}"} for i, t in enumerate(titles)]
                for name in src}

    @staticmethod
    def _kanpan():
        """注入三市场快照，避免 HTML 测试打行情接口。"""
        return dict(
            review=sources.analyze_ashare(market=sources._ASHARE_SNAPSHOT),
            hk_review=sources.analyze_hk(market=sources._HK_SNAPSHOT),
            us_review=sources.analyze_us(market=sources._US_SNAPSHOT),
        )

    def test_policy_buckets_heat_and_counts(self):
        p = sources.analyze_policy(self._brief([
            "美联储加息 25 个基点，缩表加速",
            "央行开展 5000 亿元买断式逆回购，流动性净投放",
            "美国拟对中国数据中心设备加征关税并实施出口管制",
        ]))
        tags = {b["tag"] for b in p["buckets"]}
        self.assertIn("货币政策 · 美联储", tags)
        self.assertIn("央行 · 流动性", tags)
        self.assertIn("财政 · 关税与债务", tags)
        fed = next(b for b in p["buckets"] if b["tag"] == "货币政策 · 美联储")
        self.assertEqual(fed["sources"], 1)
        self.assertEqual(fed["mentions"], 1)
        self.assertEqual(p["sources_hit"], 1)
        self.assertEqual(p["mentions"], 3)

    def test_hawkish_vs_dovish_stance(self):
        hawk = sources.analyze_policy(self._brief(["美联储鹰派发声：年内继续加息、维持缩表"]))
        dove = sources.analyze_policy(self._brief(["央行宣布降准降息，释放流动性支持实体经济"]))
        self.assertEqual(hawk["stance"], "偏鹰")
        self.assertEqual(dove["stance"], "偏鸽")

    def test_negation_flips_stance(self):
        # 「不再那么鸽派」= 立场转鹰：否定词必须把票翻转，而不是按字面计入鸽派。
        p = sources.analyze_policy(self._brief([
            "“新美联储通讯社”：贝森特政策反应函数转向不再那么鸽派",
            "Bessent policy reaction function shifts, no longer so dovish",
        ]))
        self.assertEqual(p["stance"], "偏鹰")
        self.assertGreaterEqual(p["hawk"], 2)
        self.assertEqual(p["dove"], 0)
        fed = next(b for b in p["buckets"] if b["tag"] == "货币政策 · 美联储")
        self.assertEqual(fed["evidence"][0]["stance"], "鹰派")

    def test_ascii_keywords_need_word_boundary(self):
        # FedEx / 含 fed 的普通单词不应被当成「美联储（Fed）」政策信号。
        p = sources.analyze_policy(self._brief(["FedEx 季度营收超预期，上调全年指引"]))
        self.assertEqual(p["mentions"], 0)
        self.assertEqual(p["buckets"], [])
        self.assertIn("暂无政策面信号", p["headline"])

    def test_direction_and_pressure_split(self):
        p = sources.analyze_policy(self._brief([
            "央行降准降息，流动性宽松预期利好股市",
            "伊朗海峡局势升级，制裁与战争风险警示",
        ]))
        self.assertIn("央行 · 流动性", p["up_tags"])
        self.assertIn("地缘与贸易政策", p["down_tags"])
        self.assertEqual(p["bull"], 1)
        self.assertEqual(p["bear"], 1)
        self.assertEqual(p["signals"], 2)

    def test_cross_source_dedupe(self):
        # 同一条新闻被多个源命中：整体提及按 (来源, 标题) 去重计 2 条，但热度只算 2 条独立来源。
        p = sources.analyze_policy(self._brief(
            ["美联储维持利率不变"], src=("金十数据", "财联社 电报")))
        self.assertEqual(p["mentions"], 2)
        self.assertEqual(p["sources_hit"], 2)
        fed = next(b for b in p["buckets"] if b["tag"] == "货币政策 · 美联储")
        self.assertEqual(fed["sources"], 2)

    def test_empty_brief_is_honest(self):
        p = sources.analyze_policy({})
        self.assertEqual(p["buckets"], [])
        self.assertEqual(p["mentions"], 0)
        self.assertEqual(p["stance"], "中性")
        self.assertIn("暂无政策面信号", p["headline"])
        self.assertNotIn("偏鹰", p["headline"])

    def test_demo_brief_has_policy_content(self):
        brief = {name: sources._demo_items(name) for name in sources.SOURCES}
        p = sources.analyze_policy(brief)
        self.assertTrue(p["buckets"])
        self.assertTrue(p["headline"])
        self.assertLessEqual(len(p["headline"]), 200)

    def test_analyze_brief_exposes_policy(self):
        ana = sources.analyze_brief(self._brief(["美联储加息"]))
        self.assertIn("policy", ana)
        self.assertEqual(ana["policy"]["buckets"][0]["tag"], "货币政策 · 美联储")

    def test_build_html_renders_policy_card(self):
        brief = {
            "华尔街见闻 快讯": [{"title": "“新美联储通讯社”：贝森特政策反应函数转向不再那么鸽派", "url": ""}],
            "金十数据": [
                {"title": "央行降准降息，流动性宽松利好成长板块", "url": ""},
                {"title": "伊朗海峡危机升级，制裁风险警示", "url": ""},
            ],
        }
        out = sources.build_html(brief, **self._kanpan())
        self.assertIn("AI 政策分析", out)
        self.assertIn("政策主线", out)
        self.assertIn("政策净空", out)
        self.assertIn("偏鹰", out)
        self.assertIn("条政策提及", out)
        # 位置：紧跟「AI 板块机会」，在「AI 看盘」之前。
        self.assertLess(out.index("AI 板块机会"), out.index("AI 政策分析"))
        self.assertLess(out.index("AI 政策分析"), out.index("AI 看盘"))

    def test_build_html_policy_card_honest_when_no_signals(self):
        out = sources.build_html({"金十数据": [{"title": "今天天气不错", "url": ""}]}, **self._kanpan())
        self.assertIn("AI 政策分析", out)
        self.assertIn("暂无政策面信号可统计", out)

    def test_build_html_policy_evidence_is_escaped(self):
        brief = {"金十数据": [{"title": "美联储：<script>alert(1)</script> 加息", "url": ""}]}
        out = sources.build_html(brief, **self._kanpan())
        self.assertIn("&lt;script&gt;", out)
        self.assertNotIn("<script>alert", out)


class BuildHtmlTest(unittest.TestCase):
    def _kanpan(self):
        """注入三市场快照，避免 HTML 测试打行情接口，并让看盘内容可断言。"""
        return dict(
            review=sources.analyze_ashare(market=sources._ASHARE_SNAPSHOT),
            hk_review=sources.analyze_hk(market=sources._HK_SNAPSHOT),
            us_review=sources.analyze_us(market=sources._US_SNAPSHOT),
        )

    def test_build_html_omits_monitoring_list_and_keeps_disclaimer(self):
        brief = {name: sources._demo_items(name)[:2] for name in sources.SOURCES}
        out = sources.build_html(brief, **self._kanpan())
        # 04「监测平台列表与雷达矩阵」不再作为原始来源卡片输出。
        self.assertNotIn("覆盖 18 个数据源", out)
        self.assertNotIn("金十数据 第", out)
        self.assertIn("不构成投资建议", out)

    def test_build_html_renders_four_viewpoints(self):
        brief = {name: sources._demo_items(name)[:2] for name in sources.SOURCES}
        out = sources.build_html(brief, **self._kanpan())
        for label in ("市场情绪", "多空博弈概率", "利好 / 利差板块", "资金流向分析"):
            self.assertIn(label, out)

    def test_build_html_empty_brief_renders_points_fallback(self):
        out = sources.build_html({}, **self._kanpan())
        self.assertIn("暂无可统计的多空信号", out)
        self.assertIn("资金流向分析", out)
        self.assertIn("暂无净多头信号占优的板块", out)

    def test_build_html_renders_sector_opportunity_card(self):
        # 「AI 板块机会」：机会方向（净多头排序 + 证据）与承压方向（净空头）都在简报里渲染。
        brief = {
            "华尔街见闻 快讯": [{"title": "AI 算力投资创新高，数据中心扩产超预期", "url": ""}],
            "金十数据": [
                {"title": "黄金价格暴涨创新高", "url": ""},
                {"title": "地产股债务逾期风险警示，房价下跌", "url": ""},
            ],
        }
        out = sources.build_html(brief, **self._kanpan())
        self.assertIn("AI 板块机会", out)
        self.assertIn("机会方向", out)
        self.assertIn("净多", out)
        self.assertIn("承压方向", out)
        self.assertIn("净空", out)
        # 证据要带上数据源名称
        self.assertIn("华尔街见闻 快讯", out)
        self.assertIn("基于 3 条多空信号", out)
        # 位置：紧跟「AI 每日总结」，在「AI 看盘」之前（开头 AI 部分）。
        self.assertLess(out.index("AI 每日总结"), out.index("AI 板块机会"))
        self.assertLess(out.index("AI 板块机会"), out.index("AI 看盘"))

    def test_build_html_opportunity_card_honest_when_no_signals(self):
        out = sources.build_html({}, **self._kanpan())
        self.assertIn("AI 板块机会", out)
        self.assertIn("暂无净多头信号占优的板块", out)
        self.assertNotIn("承压方向", out)

    def test_build_html_opportunity_evidence_is_escaped(self):
        brief = {"金十数据": [{"title": "AI 大模型扩产 <script>alert(1)</script> 暴涨", "url": ""}]}
        out = sources.build_html(brief, **self._kanpan())
        self.assertIn("&lt;script&gt;", out)
        self.assertNotIn("<script>alert", out)

    def test_escapes_html(self):
        out = sources.build_html({"金十数据": [{"title": "<b>x</b>", "url": ""}]}, **self._kanpan())
        # 原始来源条目不进入正文，因此也不会把未转义的 HTML 带入推送。
        self.assertNotIn("<b>x</b>", out)

    def test_build_html_length_under_pushplus_limit(self):
        # 默认 10 万字口径：即使每个源都有大量长标题快讯，生成 HTML 依然严格控制在 98,000 字以内
        huge_brief = {
            name: [{"title": f"{name} 的长标题快讯测试内容" * 3, "url": "https://example.com/test"} for _ in range(60)]
            for name in sources.SOURCES
        }
        out = sources.build_html(huge_brief, **self._kanpan())
        self.assertLessEqual(len(out), 98000)

    def test_build_html_default_quota_lists_three_per_source(self):
        # 默认仍按会员口径抓取（10 万字 / 每源 20 条），正文最后的「全网快讯」固定每源 3 条。
        self.assertEqual(sources.pushplus_quota(), (98000, 20))
        self.assertEqual(sources.default_fetch_limit(), sources.LIMIT_MEMBER)
        self.assertEqual(sources.NEWS_ITEMS_PER_SOURCE, 3)
        brief = {name: [{"title": f"快讯标题第 {i} 条", "url": ""} for i in range(8)]
                 for name in sources.SOURCES}
        out = sources.build_html(brief, **self._kanpan())
        for kept in ("快讯标题第 0 条", "快讯标题第 1 条", "快讯标题第 2 条"):
            self.assertIn(kept, out)
        for dropped in ("快讯标题第 3 条", "快讯标题第 7 条"):
            self.assertNotIn(dropped, out)
        self.assertIn("不构成投资建议", out)

    def test_build_html_news_list_is_last_and_hides_sources(self):
        # 「全网快讯」列在正文最后（免责声明与作者署名之前），且整段不出现任何数据源名称。
        # 标题用「源序号-条序」编号，保证跨源不重复，同时不含任何来源名。
        brief = {name: [{"title": f"中立标题 {si}-{i}", "url": f"https://example.com/{si}-{i}"}
                        for i in range(5)] for si, name in enumerate(sources.SOURCES)}
        out = sources.build_html(brief, **self._kanpan())
        self.assertIn("全网快讯", out)
        # 位置：AI 看盘之后、免责声明与作者署名之前。
        self.assertLess(out.index("AI 看盘"), out.index("全网快讯"))
        self.assertLess(out.index("全网快讯"), out.index("不构成投资建议"))
        self.assertLess(out.index("全网快讯"), out.index("作者：章鱼 ai"))
        card = out[out.index("全网快讯"):]
        for name in sources.SOURCES:
            self.assertNotIn(name, card)
        # 不带跳转链接，避免域名反向暴露来源。
        self.assertNotIn("<a ", card)
        self.assertNotIn("example.com", card)

    def test_build_html_news_list_dedupes_across_sources(self):
        # 来源被隐藏后，同一条新闻被多源转载只列一次。
        dup = "现货黄金上涨超过7%，报1745.93美元/盎司"
        brief = {
            "金十数据": [{"title": dup, "url": ""}, {"title": "金十独家标题", "url": ""}],
            "财联社 电报": [{"title": dup.replace("，", ", "), "url": ""}, {"title": "财联社独家标题", "url": ""}],
        }
        out = sources.build_html(brief, **self._kanpan())
        card = out[out.index("全网快讯"):]
        self.assertEqual(card.count("现货黄金上涨超过7%"), 1)
        self.assertIn("金十独家标题", card)
        self.assertIn("财联社独家标题", card)

    def test_build_html_news_list_omitted_when_brief_empty(self):
        out = sources.build_html({}, **self._kanpan())
        self.assertNotIn("全网快讯", out)
        self.assertIn("作者：章鱼 ai", out)

    def test_build_html_news_list_titles_are_escaped(self):
        brief = {"金十数据": [{"title": "<b>x</b> 快讯标题 <script>alert(1)</script>", "url": ""}]}
        out = sources.build_html(brief, **self._kanpan())
        card = out[out.index("全网快讯"):]
        self.assertIn("&lt;script&gt;", card)
        self.assertNotIn("<script>alert", card)
        self.assertNotIn("<b>x</b>", card)

    def test_build_html_free_mode_still_capped_at_20k(self):
        # 显式 PUSHPLUS_MEMBER=0 仍退回普通账号口径：抓取/容量上限 19,500 字符、快讯每源精选 3 条。
        os.environ["PUSHPLUS_MEMBER"] = "0"
        try:
            self.assertFalse(sources._is_pushplus_member())
            self.assertEqual(sources.pushplus_quota(), (19500, 3))
            self.assertEqual(sources.default_fetch_limit(), sources.LIMIT)
            huge_brief = {
                name: [{"title": f"{name} 的长标题快讯测试内容" * 3, "url": "https://example.com/t"}
                       for _ in range(60)]
                for name in sources.SOURCES
            }
            out = sources.build_html(huge_brief, **self._kanpan())
            self.assertLessEqual(len(out), 19500)
            # 快讯列表仍然在正文最后，且每源只保留 3 条。
            self.assertIn("全网快讯", out)
            brief = {name: [{"title": f"免费口径快讯第 {i} 条", "url": ""} for i in range(8)]
                     for name in sources.SOURCES}
            out2 = sources.build_html(brief, **self._kanpan())
            self.assertLessEqual(len(out2), 19500)
            for kept in ("免费口径快讯第 0 条", "免费口径快讯第 1 条", "免费口径快讯第 2 条"):
                self.assertIn(kept, out2)
            self.assertNotIn("免费口径快讯第 3 条", out2)
        finally:
            os.environ.pop("PUSHPLUS_MEMBER", None)

    def test_pushplus_quota_env_overrides(self):
        # PUSHPLUS_MAX_CHARS / PUSHPLUS_ITEMS_PER_SOURCE / BRIEF_FETCH_LIMIT 可显式覆盖，无需改代码。
        try:
            os.environ["PUSHPLUS_MAX_CHARS"] = "50000"
            os.environ["PUSHPLUS_ITEMS_PER_SOURCE"] = "6"
            os.environ["BRIEF_FETCH_LIMIT"] = "9"
            self.assertEqual(sources.pushplus_quota(), (50000, 6))
            self.assertEqual(sources.default_fetch_limit(), 9)
            os.environ["PUSHPLUS_ITEMS_PER_SOURCE"] = "all"
            self.assertEqual(sources.pushplus_quota(), (50000, None))
            # 非法值回退默认，不至于把推送配置成 0 字或负数条。
            os.environ["PUSHPLUS_MAX_CHARS"] = "abc"
            os.environ["PUSHPLUS_ITEMS_PER_SOURCE"] = "-3"
            del os.environ["PUSHPLUS_ITEMS_PER_SOURCE"]
            os.environ["PUSHPLUS_ITEMS_PER_SOURCE"] = "xyz"
            self.assertEqual(sources.pushplus_quota()[0], 98000)
            self.assertEqual(sources.pushplus_quota()[1], 20)
        finally:
            for key in ("PUSHPLUS_MAX_CHARS", "PUSHPLUS_ITEMS_PER_SOURCE", "BRIEF_FETCH_LIMIT"):
                os.environ.pop(key, None)

    def test_raw_source_cards_replaced_by_anonymous_news_list(self):
        # 04「监测平台列表与雷达矩阵」仍不渲染；原始快讯改为正文最后的匿名列表（每源 3 条）。
        brief = {name: [{"title": f"唯一原始标题 {si}-{i}", "url": ""} for i in range(3)]
                 for si, name in enumerate(sources.SOURCES)}
        out = sources.build_html(brief, **self._kanpan())
        self.assertIn("唯一原始标题", out)
        self.assertNotIn("覆盖 18 个数据源", out)
        self.assertNotIn('class="td-n td-bdr"', out)
        # 48 源 × 3 条 = 144 行，编号全表连续且不带来源名；按五大板块分组。
        total = len(sources.SOURCES) * 3
        self.assertEqual(out.count("唯一原始标题"), total)
        self.assertIn(f"共 {total} 条", out)
        self.assertIn(f">{total}</td>", out)
        card = out[out.index("全网快讯"):]
        for name in sources.SOURCES:
            self.assertNotIn(name, card)
        for sec in sources.SECTIONS:
            self.assertIn(sec["label"], card)
        self.assertIn("5 个板块", card)

    def test_build_html_custom_max_chars_shrinks_items(self):
        # 自定义较小上限时仍保证生成内容不超出推送限制。
        brief = {name: [{"title": f"{name} 的快讯标题内容示例" * 2, "url": ""} for _ in range(20)]
                 for name in sources.SOURCES}
        out_small = sources.build_html(brief, max_length=24000, **self._kanpan())
        self.assertLessEqual(len(out_small), 24000)
        self.assertIn("AI 政策分析", out_small)   # AI 板块始终保留，只收敛快讯列表

    def test_build_html_shrinks_news_list_before_dropping_it(self):
        # 字符额度越紧，快讯列表逐级收敛：3 条 → 2 条 → 1 条 → 整段省略；分析栏目始终保留。
        brief = {name: [{"title": f"快讯条目 {si}-{i}：撑开字符额度的较长标题内容示例文本", "url": ""}
                        for i in range(20)] for si, name in enumerate(sources.SOURCES)}
        n = len(sources.SOURCES)
        full = sources.build_html(brief, **self._kanpan())
        self.assertEqual(full.count("快讯条目"), n * 3)
        two = sources.build_html(brief, max_length=len(full) - 100, **self._kanpan())
        self.assertEqual(two.count("快讯条目"), n * 2)
        one = sources.build_html(brief, max_length=len(two) - 100, **self._kanpan())
        self.assertEqual(one.count("快讯条目"), n)
        none = sources.build_html(brief, max_length=len(one) - 100, **self._kanpan())
        self.assertNotIn("全网快讯", none)
        self.assertNotIn("快讯条目", none)
        for out in (two, one, none):
            self.assertIn("AI 每日总结", out)
            self.assertIn("AI 政策分析", out)
            self.assertIn("AI 看盘", out)
            self.assertIn("作者：章鱼 ai", out)


class AshareReviewTest(unittest.TestCase):
    """最新 A 股六维度复盘：内容策略、数据解析、复盘日选取、离线兜底与 HTML 渲染。"""

    CANDLE = ("2026-08-27,3911.89,3956.57,3958.03,3909.31,516777549,"
              "1010226573954.60,1.25,1.13,44.05,1.07")

    def test_parse_candle(self):
        candle = sources._parse_ashare_candle(self.CANDLE)
        self.assertEqual(candle["date"], "2026-08-27")
        self.assertEqual(candle["close"], 3956.57)
        self.assertEqual(candle["pct"], 1.13)
        self.assertEqual(candle["change"], 44.05)
        self.assertEqual(candle["amount"], 1010226573954.60)
        self.assertEqual(candle["source"], "eastmoney")
        self.assertIsNone(sources._parse_ashare_candle(""))

    def test_parse_tencent_candle(self):
        # 备用源（腾讯）行格式：[date, open, close, high, low, volume]，涨跌由前收推算。
        row = ["2026-08-28", "3911.89", "3956.57", "3958.03", "3909.31", "516777549.00"]
        candle = sources._parse_tencent_candle(row, prev_close=3912.52)
        self.assertEqual(candle["date"], "2026-08-28")
        self.assertEqual(candle["close"], 3956.57)
        self.assertEqual(candle["change"], 44.05)
        self.assertEqual(candle["pct"], 1.13)
        self.assertIsNone(candle["amount"])  # 腾讯日 K 无成交额字段
        self.assertEqual(candle["source"], "tencent")
        # 首行无前收：pct/change 置 None（由抓取层丢弃，只用于校准）。
        first = sources._parse_tencent_candle(row, prev_close=None)
        self.assertIsNone(first["pct"])
        self.assertIsNone(first["change"])
        # 非法输入
        self.assertIsNone(sources._parse_tencent_candle(None, 1.0))
        self.assertIsNone(sources._parse_tencent_candle(["2026-08-28", "x", "y"], 1.0))

    def test_fetch_klines_backup_fills_missing_indices(self):
        # 主源（东方财富）失联/缺指数时，备用源（腾讯）自动补位；主源已有的指数不被覆盖。
        em_candle = sources._parse_ashare_candle(self.CANDLE)
        orig_em = sources._fetch_ashare_klines_eastmoney
        orig_tx = sources._fetch_ashare_klines_tencent
        tx_candle = sources._parse_tencent_candle(
            ["2026-08-27", "3911.89", "3900.00", "3958.03", "3909.31", "1"], prev_close=3850.0)
        try:
            # 场景一：主源全挂 → 全部来自备用源。
            sources._fetch_ashare_klines_eastmoney = lambda: {}
            sources._fetch_ashare_klines_tencent = lambda: {
                name: {"2026-08-27": dict(tx_candle)}
                for name, _ in sources._ASHARE_TX_SYMBOLS
            }
            klines = sources._fetch_ashare_klines()
            self.assertEqual(len(klines), 4)
            self.assertEqual(klines["上证指数"]["2026-08-27"]["source"], "tencent")

            # 场景二：主源只缺一个指数 → 备用源只补缺口，不覆盖主源数据。
            sources._fetch_ashare_klines_eastmoney = lambda: {
                "上证指数": {"2026-08-27": dict(em_candle)},
                "深证成指": {"2026-08-27": dict(em_candle)},
                "创业板指": {"2026-08-27": dict(em_candle)},
            }
            klines = sources._fetch_ashare_klines()
            self.assertEqual(klines["上证指数"]["2026-08-27"]["source"], "eastmoney")
            self.assertEqual(klines["科创50"]["2026-08-27"]["source"], "tencent")

            # 场景三：主源齐全 → 不触发备用源。
            def _boom():
                raise AssertionError("主源齐全时不应调用备用源")
            sources._fetch_ashare_klines_eastmoney = lambda: {
                name: {"2026-08-27": dict(em_candle)} for name, _ in sources._ASHARE_INDICES
            }
            sources._fetch_ashare_klines_tencent = _boom
            klines = sources._fetch_ashare_klines()
            self.assertEqual(len(klines), 4)
        finally:
            sources._fetch_ashare_klines_eastmoney = orig_em
            sources._fetch_ashare_klines_tencent = orig_tx

    def test_build_market_from_tencent_backup(self):
        # 完全由备用源组装：source=tencent，成交额（备用源无此字段）自动降级为 None。
        orig_pools = sources._fetch_ashare_pools
        sources._fetch_ashare_pools = lambda review_date: {
            "limit_up": None, "limit_down": None, "hot_sectors": [], "cold_sectors": []}
        try:
            candle = sources._parse_tencent_candle(
                ["2026-08-28", "3911.89", "3956.57", "3958.03", "3909.31", "1"],
                prev_close=3912.52)
            klines = {name: {"2026-08-28": dict(candle)}
                      for name, _ in sources._ASHARE_TX_SYMBOLS}
            market = sources._build_ashare_market(klines, date(2026, 8, 28))
        finally:
            sources._fetch_ashare_pools = orig_pools
        self.assertEqual(market["source"], "tencent")
        self.assertEqual(market["date"], "2026-08-28")
        self.assertEqual(len(market["indices"]), 4)
        self.assertIsNone(market["turnover"])

    def test_pick_review_date_is_latest_trading_day(self):
        # 今天 2026-08-29（周六）→ 最近交易日 = 2026-08-28（周五）。
        klines = {
            "上证指数": {"2026-08-27": {}, "2026-08-28": {}},
            "深证成指": {"2026-08-27": {}},
        }
        from datetime import date
        self.assertEqual(sources._pick_review_date(klines, date(2026, 8, 29)), "2026-08-28")
        # 周一 2026-08-31（接口已有当天日 K）：直接复盘 2026-08-31。
        klines_mon = {
            "上证指数": {"2026-08-28": {}, "2026-08-31": {}},
            "深证成指": {"2026-08-28": {}, "2026-08-31": {}},
        }
        self.assertEqual(sources._pick_review_date(klines_mon, date(2026, 8, 31)), "2026-08-31")
        # 周一 2026-08-31（盘前接口仅到周五）：自动回溯到 2026-08-28。
        self.assertEqual(sources._pick_review_date(klines, date(2026, 8, 31)), "2026-08-28")

    def test_get_fallback_review_date(self):
        from datetime import date
        # 周日 2026-08-30 → 最近交易日周五 2026-08-28
        self.assertEqual(sources._get_fallback_review_date(date(2026, 8, 30)), "2026-08-28")
        # 周一 2026-08-31 → 当天 2026-08-31
        self.assertEqual(sources._get_fallback_review_date(date(2026, 8, 31)), "2026-08-31")
        # 周六 2026-08-29 → 周五 2026-08-28
        self.assertEqual(sources._get_fallback_review_date(date(2026, 8, 29)), "2026-08-28")
        # 周五 2026-08-28 → 当天 2026-08-28
        self.assertEqual(sources._get_fallback_review_date(date(2026, 8, 28)), "2026-08-28")

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
        self.assertIn("AI 看盘", texts["后市观点与策略"])
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
        hk_review = sources.analyze_hk(market=sources._HK_SNAPSHOT)
        us_review = sources.analyze_us(market=sources._US_SNAPSHOT)
        out = sources.build_html(brief, review=review, hk_review=hk_review, us_review=us_review)
        self.assertIn("AI 看盘", out)
        # 05「数据获取与时间核对」不进入正文；行情分析本身仍保留。
        self.assertNotIn(sources._ASHARE_SNAPSHOT["date"], out)
        self.assertNotIn("东方财富行情接口", out)
        for label in ("三大指数", "两市成交额", "涨跌家数与涨跌停",
                      "领涨 / 领跌板块", "主力资金与北向资金", "后市观点与策略"):
            self.assertIn(label, out)
        self.assertIn("偏多", out)
        # 同一张「AI 看盘」卡覆盖 A 股 / 港股 / 美股。
        self.assertIn("港股", out)
        self.assertIn("美股", out)
        self.assertIn("恒生指数", out)
        self.assertIn("纳斯达克", out)
        self.assertIn("南向资金", out)
        self.assertIn("资金与避险", out)

    def test_review_sector_names_are_escaped(self):
        market = dict(sources._ASHARE_SNAPSHOT)
        market["leaders"] = [{"name": "<算力>", "note": "x"}]
        market["laggards"] = [{"name": "银行", "note": "x"}]
        brief = {"金十数据": [{"title": "x", "url": ""}]}
        out = sources.build_html(
            brief,
            review=sources.analyze_ashare(market=market),
            hk_review=sources.analyze_hk(market=sources._HK_SNAPSHOT),
            us_review=sources.analyze_us(market=sources._US_SNAPSHOT),
        )
        self.assertIn("&lt;算力&gt;", out)
        self.assertNotIn("<算力>", out)


class OverseasReviewTest(unittest.TestCase):
    """港股 / 美股看盘：六维度内容、离线兜底与 HTML 渲染。"""

    def test_analyze_hk_has_six_dimensions(self):
        review = sources.analyze_hk(market=sources._HK_SNAPSHOT)
        self.assertEqual(review["date"], sources._HK_SNAPSHOT["date"])
        self.assertEqual(
            [p["label"] for p in review["points"]],
            ["三大指数", "港股成交额", "涨跌家数",
             "领涨 / 领跌板块", "南向资金", "后市观点与策略"],
        )
        self.assertTrue(all(p["text"] for p in review["points"]))
        self.assertIn(review["bias"], ("偏多", "偏空", "中性"))
        self.assertEqual(review["market"], "hk")

    def test_analyze_hk_snapshot_content(self):
        review = sources.analyze_hk(market=sources._HK_SNAPSHOT)
        texts = {p["label"]: p["text"] for p in review["points"]}
        self.assertIn("25842.16", texts["三大指数"])
        self.assertIn("恒生科技", texts["三大指数"])
        self.assertIn("1,862 亿港元", texts["港股成交额"])
        self.assertIn("超1200只", texts["涨跌家数"])
        self.assertIn("科技硬件", texts["领涨 / 领跌板块"])
        self.assertIn("地产", texts["领涨 / 领跌板块"])
        self.assertIn("南向资金", texts["南向资金"])
        self.assertIn("AI 看盘", texts["后市观点与策略"])
        self.assertIn("高盛", texts["后市观点与策略"])

    def test_analyze_us_has_six_dimensions(self):
        review = sources.analyze_us(market=sources._US_SNAPSHOT)
        self.assertEqual(review["date"], sources._US_SNAPSHOT["date"])
        self.assertEqual(
            [p["label"] for p in review["points"]],
            ["三大指数", "美股成交额", "涨跌家数",
             "领涨 / 领跌板块", "资金与避险", "后市观点与策略"],
        )
        self.assertTrue(all(p["text"] for p in review["points"]))
        self.assertIn(review["bias"], ("偏多", "偏空", "中性"))
        self.assertEqual(review["market"], "us")

    def test_analyze_us_snapshot_content(self):
        review = sources.analyze_us(market=sources._US_SNAPSHOT)
        texts = {p["label"]: p["text"] for p in review["points"]}
        self.assertIn("6488.20", texts["三大指数"])
        self.assertIn("纳斯达克", texts["三大指数"])
        self.assertIn("4,820 亿美元", texts["美股成交额"])
        self.assertIn("半导体", texts["领涨 / 领跌板块"])
        self.assertIn("能源", texts["领涨 / 领跌板块"])
        self.assertIn("VIX", texts["资金与避险"])
        self.assertIn("AI 看盘", texts["后市观点与策略"])
        self.assertIn("英伟达", texts["后市观点与策略"])

    def test_hk_us_headline_mentions_leaders(self):
        hk = sources.analyze_hk(market=sources._HK_SNAPSHOT)
        self.assertIn("科技硬件", hk["headline"])
        self.assertIn("恒生科技", hk["headline"])
        us = sources.analyze_us(market=sources._US_SNAPSHOT)
        self.assertIn("半导体", us["headline"])
        self.assertIn("纳斯达克", us["headline"])

    def test_get_hk_us_market_falls_back_offline(self):
        original = sources.urlopen

        def _offline(*args, **kwargs):
            raise OSError("network unreachable")

        sources.urlopen = _offline
        try:
            hk = sources.get_hk_market()
            us = sources.get_us_market()
        finally:
            sources.urlopen = original
        self.assertEqual(hk["date"], sources._get_fallback_review_date())
        self.assertEqual(hk["source"], "snapshot")
        self.assertEqual(us["date"], sources._get_fallback_review_date())
        self.assertEqual(us["source"], "snapshot")

    def test_build_simple_market_from_klines(self):
        candle = sources._parse_ashare_candle(
            "2026-08-28,25000.0,25842.16,25900.0,24900.0,1000000,186200000000.0,1.8,1.28,326.40,1.0")
        klines = {name: {"2026-08-28": dict(candle)} for name, _ in sources._HK_INDICES}
        market = sources._build_simple_market(
            klines, date(2026, 8, 28),
            [name for name, _ in sources._HK_INDICES], sources._HK_SNAPSHOT,
            turnover_names=["恒生指数"], turnover_unit="亿港元",
        )
        self.assertEqual(market["source"], "eastmoney")
        self.assertEqual(market["date"], "2026-08-28")
        self.assertEqual(len(market["indices"]), 3)
        self.assertEqual(market["turnover"]["amount"], 1862)
        self.assertEqual(market["turnover"]["unit"], "亿港元")


class MarketFreshnessTest(unittest.TestCase):
    """推送前大盘数据新鲜度检查：不是最新就不推。

    行情接口全部走本地注入的日 K，杜绝测试依赖外网。
    场景基准：today = 2026-08-31（周一），最新日 K = 2026-08-31。
    """

    TODAY = date(2026, 8, 31)
    EXPECTED = "2026-08-31"

    def setUp(self):
        self._orig_klines = sources._fetch_ashare_klines
        self._orig_pools = sources._fetch_ashare_pools
        # 涨停/跌停池与网络无关：注入空结果即可。
        sources._fetch_ashare_pools = lambda review_date: {
            "limit_up": None, "limit_down": None, "hot_sectors": [], "cold_sectors": []}

    def tearDown(self):
        sources._fetch_ashare_klines = self._orig_klines
        sources._fetch_ashare_pools = self._orig_pools
        os.environ.pop("MARKET_FRESHNESS_FORCE", None)

    def _klines(self, *dates):
        """构造四大指数的日 K：{指数名: {日期: candle}}。"""
        out = {}
        for name in ("上证指数", "深证成指", "创业板指", "科创50"):
            out[name] = {
                d: sources._parse_ashare_candle(
                    f"{d},3900.0,3950.0,3960.0,3890.0,1000000,200000000000.0,1.8,1.28,50.0,1.0")
                for d in dates
            }
        return out

    def _tx_klines(self, *dates):
        """构造四大指数的备用源（腾讯）日 K：无成交额，涨跌由前收推算。"""
        out = {}
        for name in ("上证指数", "深证成指", "创业板指", "科创50"):
            candles = {}
            prev_close = 3900.0
            for d in dates:
                candle = sources._parse_tencent_candle(
                    [d, "3900.0", "3950.0", "3960.0", "3890.0", "1"], prev_close)
                candles[d] = candle
                prev_close = candle["close"]
            out[name] = candles
        return out

    def test_fresh_market_passes_gate(self):
        # 接口正常：最新日 K = 今天，复盘日 = 2026-08-31 → 放行。
        klines = self._klines("2026-08-26", "2026-08-27", "2026-08-28", "2026-08-31")
        market = sources._build_ashare_market(klines, self.TODAY)
        fresh = sources.check_market_freshness(market, klines=klines, today=self.TODAY)
        self.assertTrue(fresh["ok"], fresh["reason"])
        self.assertEqual(fresh["market_date"], self.EXPECTED)
        self.assertEqual(fresh["expected_date"], self.EXPECTED)
        self.assertEqual(fresh["latest_kline_date"], "2026-08-31")
        self.assertEqual(fresh["source"], "eastmoney")
        self.assertIn("最新", fresh["reason"])

    def test_tencent_backup_market_passes_gate(self):
        # 主源失联但备用源（腾讯）数据最新：source=tencent 同样放行。
        klines = self._tx_klines("2026-08-26", "2026-08-27", "2026-08-28", "2026-08-31")
        market = sources._build_ashare_market(klines, self.TODAY)
        fresh = sources.check_market_freshness(market, klines=klines, today=self.TODAY)
        self.assertTrue(fresh["ok"], fresh["reason"])
        self.assertEqual(fresh["source"], "tencent")
        self.assertEqual(fresh["market_date"], self.EXPECTED)
        self.assertIn("备用", fresh["reason"])

    def test_offline_snapshot_is_blocked(self):
        # 行情接口不可用 → 无法确认数据新旧 → 拦截（宁可不放行）。
        fresh = sources.check_market_freshness(klines={}, today=self.TODAY)
        self.assertFalse(fresh["ok"])
        self.assertIn("行情接口不可用", fresh["reason"])
        self.assertEqual(fresh["source"], "snapshot")

    def test_lagging_feed_is_blocked(self):
        # 接口能通，但最新日 K 早于内置快照基线 → 行情源异常 → 拦截。
        klines = self._klines("2026-08-19", "2026-08-20")
        market = sources._build_ashare_market(klines, self.TODAY)
        fresh = sources.check_market_freshness(market, klines=klines, today=self.TODAY)
        self.assertFalse(fresh["ok"])
        self.assertIn("滞后", fresh["reason"])

    def test_stale_review_date_is_blocked(self):
        # 数据来源是实时接口，但复盘日落后于应复盘交易日 → 拦截。
        klines = self._klines("2026-08-26", "2026-08-27", "2026-08-28", "2026-08-31")
        market = {"date": "2026-08-28", "source": "eastmoney"}
        fresh = sources.check_market_freshness(market, klines=klines, today=self.TODAY)
        self.assertFalse(fresh["ok"])
        self.assertIn("不一致", fresh["reason"])

    def test_snapshot_fallback_is_blocked_even_if_date_matches(self):
        # 即便快照日期恰好等于应复盘日，数值也是冻结的旧数据 → 仍按非最新拦截。
        klines = self._klines("2026-08-26", "2026-08-27", "2026-08-28", "2026-08-31")
        market = {"date": self.EXPECTED, "source": "snapshot"}
        fresh = sources.check_market_freshness(market, klines=klines, today=self.TODAY)
        self.assertFalse(fresh["ok"])
        self.assertIn("内置快照", fresh["reason"])

    def test_collect_market_for_push_returns_both(self):
        # 推送入口：一次抓取同时返回 market 与 freshness，且两者指向同一份日 K。
        klines = self._klines("2026-08-27", "2026-08-28", "2026-08-31")
        sources._fetch_ashare_klines = lambda: klines
        market, fresh = sources.collect_market_for_push()
        self.assertEqual(market["date"], self.EXPECTED)
        self.assertTrue(fresh["ok"], fresh["reason"])

    def test_force_env_pins_gate_result(self):
        # MARKET_FRESHNESS_FORCE=fresh|stale（测试/应急）可以强制检查结果。
        klines = self._klines("2026-08-27", "2026-08-28", "2026-08-31")
        sources._fetch_ashare_klines = lambda: klines

        os.environ["MARKET_FRESHNESS_FORCE"] = "stale"
        _, fresh = sources.collect_market_for_push()
        self.assertFalse(fresh["ok"])
        self.assertTrue(fresh.get("forced"))
        self.assertIn("MARKET_FRESHNESS_FORCE=stale", fresh["reason"])

        os.environ["MARKET_FRESHNESS_FORCE"] = "fresh"
        _, fresh = sources.collect_market_for_push()
        self.assertTrue(fresh["ok"])
        self.assertTrue(fresh.get("forced"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
