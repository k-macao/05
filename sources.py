#!/usr/bin/env python3
"""章鱼 AI·全景分析 —— 18 个数据源抓取采集器（零第三方依赖，仅标准库）。

为什么这么设计
------------
- 华尔街见闻 / 雪球 / 金十 / 法布等站点页面为 **前端 JS 渲染**，部分还需登录，
  直接 GET 只能拿到空壳，无法解析出条目。
- 因此每个源同时记录“源头站”(origin) 与一个公开的**热榜聚合通道** rebang.vip
  （该聚合页为服务端渲染，标题与链接均回指源头站原文，是稳定的抓取通道）。
- 新增 6 个热搜/热点源（知乎、抖音、微博、虎扑、AI Hot、Google news 中文）来自
  ourongxing/newsnow 项目，使用直接 API / HTML 抓取。
- 抓取顺序：自定义收集器 / 聚合通道 → 内置演示数据兜底，
  保证任何环境（本地 / GitHub Pages / GitHub Actions）都能稳定出结果。

对外接口
--------
    SOURCES            : 18 个源的名称列表（与前端 /api/sources、推送保持一致）
    SOURCE_META        : 每个源的元信息（name / origin / channel / collector）
    collect_all()      : 依次抓取全部 18 个源，返回 {name: [item, ...]}
    collect_one(name)  : 抓取单个源，返回 [item, ...]
    analyze_brief()    : 本地「AI 总结」引擎（主题热度 + 多空博弈概率）
    get_ashare_market(): 采集「前天」A 股行情（东方财富主接口 → 腾讯证券备用接口 → 内置快照兜底）
    analyze_ashare()   : 最新 A 股六维度复盘引擎（三大指数/成交额/涨跌家数/板块/资金/后市）
    check_market_freshness() : 大盘数据新鲜度检查（推送前闸门：不是最新就不推）
    collect_market_for_push(): 推送入口专用，一次抓取返回 (market, freshness)
    build_html(brief)  : 由采集结果生成适合微信阅读的 HTML 简报
"""
from __future__ import annotations

import html
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen, build_opener, HTTPCookieProcessor

TIMEOUT = 8
LIMIT = 5             # 每个源默认取前 5 条
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# ---------------------------------------------------------------- 源定义
# channel 为 rebang.vip 聚合页路径；origin 为源头站域名（用于解析链接过滤/直连）。
SOURCE_META = [
    {"name": "MKTNews 快讯",    "origin": "mktnews.net",            "channel": "https://www.rebang.vip/mktnews/hot-list"},
    {"name": "华尔街见闻 快讯",  "origin": "wallstreetcn.com",        "channel": "https://www.rebang.vip/wallstreetcn/quick"},
    {"name": "华尔街见闻最新",   "origin": "wallstreetcn.com",        "channel": "https://www.rebang.vip/wallstreetcn/hot-news"},
    {"name": "华尔街见闻 最热",  "origin": "wallstreetcn.com",        "channel": "https://www.rebang.vip/wallstreetcn/hot-list"},
    {"name": "财联社 电报",      "origin": "cls.cn",                 "channel": "https://www.rebang.vip/cailianshe/telegram"},
    {"name": "财联社 深度",      "origin": "cls.cn",                 "channel": "https://www.rebang.vip/cailianshe/depth"},
    {"name": "财联社 热门",      "origin": "cls.cn",                 "channel": "https://www.rebang.vip/cailianshe/hot-list"},
    {"name": "雪球 热门股票",    "origin": "xueqiu.com",             "channel": "https://www.rebang.vip/xueqiu/7-24-hot"},
    {"name": "格隆汇 事件",      "origin": "gelonghui.com",          "channel": "https://www.rebang.vip/gelonghui/hot-list"},
    {"name": "法布财经 快讯",    "origin": "fastbull.com",           "channel": "https://www.rebang.vip/fabubaijiance/hot-express"},
    {"name": "法布财经 头条",    "origin": "fastbull.com",           "channel": "https://www.rebang.vip/fabubaijiance/hot-news"},
    {"name": "金十数据",        "origin": "jin10.com",              "channel": "https://www.rebang.vip/jinshishuju/hot-list"},
    # --- 新增 6 个热搜/热点源（来自 ourongxing/newsnow 项目）---
    {"name": "知乎热榜",        "collector": "zhihu"},
    {"name": "抖音热搜",        "collector": "douyin"},
    {"name": "微博实时热搜",    "collector": "weibo"},
    {"name": "虎扑热搜",        "collector": "hupu"},
    {"name": "AI Hot",          "collector": "aihot"},
    {"name": "Google news 中文", "collector": "google_news"},
]

SOURCES = [m["name"] for m in SOURCE_META]

# 兜底演示数据：网络不可用时返回，保证任何环境都能出简报。
_DEMO = {
    "MKTNews 快讯": [
        "TIMIRAOS: BESSENT policy reaction function shifts, no longer so dovish",
        "Procter & Gamble (PG.N) +1% on report it will buy Thorne for $3.8B",
        "Iran FM: talks aim to safeguard sovereign rights of Iran and Oman",
        "Lockheed in talks to buy U.S. scandium / germanium from NioCorp, Teck, 5N Plus",
        "EasyJet French cabin crew union filed strike notice (Aug 7 - Sep 2)",
    ],
    "华尔街见闻 快讯": [
        "淡水河谷CEO：伊朗战争造成诸多项目的速度放缓",
        "诺和诺德2026年业绩前景改善，谈及GLP-1销售",
        "“新美联储通讯社”：贝森特政策反应函数转向不再那么鸽派",
        "USA Rare Earth 涨幅扩大至8.9%，洛克希德·马丁洽购美国矿山关键矿产",
        "标普500涨幅扩大至1.5%，道指涨925点，半导体指数涨超6%",
    ],
    "华尔街见闻最新": [
        "市场错判了AI？云业务积压订单暴增150%达1.7万亿美元",
        "沙特阿美Q2净利暴增33%，CEO警告海峡封锁引发“历史最大石油供应冲击”",
        "Citadel证券：美股7月暴跌不是牛市终结，而是“技术性重置”",
        "7月楼市淡季不淡：多城成交同比保持增长，上海豪宅开盘日光",
        "美国6月JOLTS职位空缺超预期回落，裁员有限、招聘回升",
    ],
    "华尔街见闻 最热": [
        "华尔街见闻早餐FM-Radio | 2026年8月4日",
        "美国拟禁止进口中国新型数据中心设备，我使馆：敦促美停止抹黑中企并威胁制裁",
        "美股8月开门红，道指新高，亚马逊市值首破三万亿，原油重挫",
        "罕见干预操作！贝森特抛欧元、指示美联储“借钱”，让日本“别抛美债”",
        "创业板暴涨超5.6%，算力硬件全线反攻、光通信“满屏涨停”",
    ],
    "财联社 电报": [
        "诺和诺德预计本财年固定汇率口径调整后销售额同比-6%至0%",
        "伊朗外交部发言人：与阿曼在霍尔木兹海峡过境问题谈判仍在继续",
        "日本古河电工宣布投资1000亿日元扩大光纤产能 目标产能翻倍",
        "Blue Owl完成欧洲净租赁基金募集，总承诺资本超16亿欧元",
        "摩根大通据悉接近达成收购Antin旗下法国区域制冷网络供应商的交易",
    ],
    "财联社 深度": [
        "债务逾期、25起诉讼待解、公司及实控人被立案 联创光电面临多重危机",
        "Anthropic再掀算力争夺战：据称斥资100亿美元抢占数据中心资源",
        "又有海外光纤巨头宣布产能翻倍计划 已获得客户长期采购承诺",
        "AI泡沫争议未阻热情 亿万富豪家族办公室竞逐机器人赛道",
        "贝森特详解美日联手干预日元：防止弱日元冲击亚洲市场稳定",
    ],
    "财联社 热门": [
        "L3、L4级自动驾驶“强标”明年7月实施 明确安全主体责任、接管机制",
        "央行将开展5000亿元买断式逆回购 8月流动性面临两大扰动",
        "日元又成了全世界的问题？全球最关键套利交易遭“降维打击”",
        "一图看懂｜业绩炸场！CXO“盈利王”强势涨停带动板块修复",
        "多家券商股东出手增持！是稳信心，更是直接开拿低价筹码",
    ],
    "雪球 热门股票": [
        "据Argus Media，法国玉米产量降至690万吨，创最近50年新低",
        "现货铂金上涨超过7%，报1,745.93美元/盎司",
        "【诺和诺德上调2026年调整后销售额和调整后营业利润预期】",
        "伊朗外交部发言人：与阿曼在霍尔木兹海峡过境问题谈判仍在继续",
        "【日本古河电工宣布投资1000亿日元扩大光纤产能 目标产能翻倍】",
    ],
    "格隆汇 事件": [
        "矽电股份(301629)：将继续聚焦探针台领域",
        "盛达资源(000603.SZ)：预计妙皇铜铅锌银矿矿山建设总投资6-7亿元",
        "鲁西化工(000830.SZ)：今年加大产品出口力度，提高国外收入占比",
        "胜通能源(001331.SZ)：七腾机器人生产基地主要位于重庆、合肥等",
        "美股异动丨麦当劳涨超2%，Q2调整后每股收益超预期",
    ],
    "法布财经 快讯": [
        "现货钯金上涨超过7%，报1,745.93美元/盎司",
        "淡水河谷CEO：伊朗战争造成诸多项目的速度放缓",
        "现货铂金上涨超过7%，报1,745.93美元/盎司",
        "“美联储传声筒”：贝森特政策反应函数转向不再那么鸽派",
        "钯金期货日内涨8%，现报1358.00美元/盎司",
    ],
    "法布财经 头条": [
        "特朗普押注最后谈判机会，日元干预规模再创高位",
        "中国内地企业在香港上市指南：条件、流程、优势及注意事项",
        "吴清支持内地企业香港上市：政策信号与市场影响",
        "美伊暂缓军事冲突，日元迎美日联合干预",
        "日本疑似出手干预汇市，美伊冲突外溢风险升温",
    ],
    "金十数据": [
        "现货钯金上涨超过7%，报1,745.93美元/盎司",
        "诺和诺德(NVO.N)：第二季度营业利润受到美国340B返利拨备转回的负面影响",
        "阿根廷出口与加工商会CIARA-CEC：阿根廷港口工人罢工影响超过45艘船只",
        "诺和诺德：2026年第二季度调整后销售额784.9亿丹麦克朗、营业利润333.9亿",
        "“美联储传声筒”：贝森特政策反应函数转向不再那么鸽派",
    ],
    "知乎热榜": [
        "如何看待 2026 年高考录取分数线公布？",
        "为什么现在的年轻人越来越喜欢独居？",
        "有哪些让你觉得「涨知识了」的冷知识？",
        "如何评价电影《奥本海默》？",
        "你经历过的最离谱的骗局是什么？",
    ],
    "抖音热搜": [
        "高考加油 为梦想而战",
        "今日份好消息分享",
        "夏天就要吃西瓜",
        "旅行推荐 避暑胜地",
        "职场新人避坑指南",
        "抖音电商新趋势",
        "周杰伦演唱会门票抢购",
        "如何在家做冰镇咖啡",
        "自驾游路线推荐",
        "职场高效办公插件",
    ],
    "微博实时热搜": [
        "高考成绩陆续公布",
        "某明星官宣结婚",
        "暑期档电影推荐",
        "高温预警 注意防暑",
        "国足世预赛最新战报",
        "杭州亚运会筹备进展",
        "SpaceX 发射最新进展",
        "苹果发布会预测",
        "今日影讯早知道",
        "专家谈年轻人理财",
    ],
    "虎扑热搜": [
        "NBA 总决赛 G7 赛后讨论",
        "欧冠决赛精彩回顾",
        "步行街主干道 今日热议",
        "球鞋发售日历 8月新款",
        "电竞 S赛 战队分析",
    ],
    "AI Hot": [
        "OpenAI 发布 GPT-5 技术预览版",
        "Anthropic Claude 4 性能基准测试",
        "Google DeepMind 新论文：多模态推理",
        "开源大模型 Llama 4 发布",
        "AI 编程助手效率对比评测",
    ],
    "Google news 中文": [
        "全球科技巨头发布财报，AI 支出超预期",
        "亚太股市周一开盘走势分化",
        "美联储会议纪要暗示通胀路径仍存不确定性",
        "新能源汽车全球销量创历史新高",
        "全球气候峰会达成初步减排协议",
    ],
}


# ---------------------------------------------------------------- HTML 链接解析
class LinkCollector(HTMLParser):
    """收集页面中所有 <a href=...>text</a> 的 (href, text)。"""
    def __init__(self):
        super().__init__()
        self._href = None
        self._buf = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            d = dict(attrs)
            self._href = d.get("href")
            self._buf = []

    def handle_data(self, data):
        if self._href is not None:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            text = "".join(self._buf).strip()
            if text:
                self.links.append((self._href, text))
            self._href = None
            self._buf = []


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _clean_title(text: str) -> str:
    """聚合页里条目标题通常带一个相对时间前缀（如『19分钟前』），去掉它。"""
    t = _collapse(text)
    # 形如 "19分钟前 标题" / "1小时前 标题" / "1天前 标题"
    m = re.match(r"^(\d+[分钟小时天]\S*)\s+(.+)$", t)
    return m.group(2) if m else t


def _fetch(url: str) -> str:
    req = Request(url, headers={"User-Agent": UA}, method="GET")
    with urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8", "replace")


def _filter_items(links, origin: str, limit: int):
    """从 (href, text) 列表里筛出指向源头站的条目：去重、清理、截断。纯函数，便于测试。"""
    seen, items = set(), []
    for href, text in links:
        if origin not in href or href in seen:
            continue
        seen.add(href)
        title = _clean_title(text)
        if not title:
            continue
        items.append({"title": title, "url": href})
        if len(items) >= limit:
            break
    return items


def _parse_channel(url: str, origin: str, limit: int):
    """抓取聚合页并提取指向源头站的条目（去重、截断）。"""
    raw = _fetch(url)
    parser = LinkCollector()
    parser.feed(raw)
    return _filter_items(parser.links, origin, limit)


def _demo_items(name: str) -> list:
    return [{"title": t, "url": ""} for t in _DEMO.get(name, [])]


# ---------------------------------------------------------------- 新增 6 个源的抓取器
# 这些源使用直接 API / HTML 抓取（参考 ourongxing/newsnow 项目实现）

def _collect_zhihu(limit: int) -> list:
    """知乎热榜 - 直接 API 抓取。"""
    url = "https://www.zhihu.com/api/v3/feed/topstory/hot-list-web?limit=20&desktop=true"
    req = Request(url, headers={"User-Agent": UA}, method="GET")
    with urlopen(req, timeout=TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    items = []
    for k in data.get("data", [])[:limit]:
        target = k.get("target", {})
        title = target.get("title_area", {}).get("text", "")
        link = target.get("link", {}).get("url", "")
        if title:
            items.append({"title": title, "url": link})
    return items


def _collect_douyin(limit: int) -> list:
    """抖音热搜 - 需要先获取 cookie。"""
    # 先从 login.douyin.com 获取 cookie
    cookie_jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(cookie_jar))
    try:
        opener.open("https://login.douyin.com/", timeout=TIMEOUT)
    except (HTTPError, URLError, TimeoutError):
        return []
    
    # 用获取的 cookie 请求热搜 API
    url = "https://www.douyin.com/aweme/v1/web/hot/search/list/?device_platform=webapp&aid=6383&channel=channel_pc_web&detail_list=1"
    req = Request(url, headers={"User-Agent": UA}, method="GET")
    try:
        with opener.open(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError):
        return []
    
    items = []
    for k in data.get("data", {}).get("word_list", [])[:limit]:
        word = k.get("word", "")
        sentence_id = k.get("sentence_id", "")
        if word and sentence_id:
            items.append({
                "title": word,
                "url": f"https://www.douyin.com/hot/{sentence_id}"
            })
    return items


class WeiboTableParser(HTMLParser):
    """解析微博热搜表格。"""
    def __init__(self):
        super().__init__()
        self._in_table = False
        self._in_tbody = False
        self._in_tr = False
        self._in_td_02 = False
        self._in_a = False
        self._current_href = None
        self._current_text = []
        self.items = []
    
    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "table":
            self._in_table = True
        elif tag == "tbody" and self._in_table:
            self._in_tbody = True
        elif tag == "tr" and self._in_tbody:
            self._in_tr = True
        elif tag == "td" and self._in_tr:
            cls = d.get("class", "")
            if "td-02" in cls:
                self._in_td_02 = True
        elif tag == "a" and self._in_td_02:
            href = d.get("href", "")
            if href and "javascript:void(0);" not in href:
                self._in_a = True
                self._current_href = href
                self._current_text = []
    
    def handle_data(self, data):
        if self._in_a:
            self._current_text.append(data)
    
    def handle_endtag(self, tag):
        if tag == "a" and self._in_a:
            title = "".join(self._current_text).strip()
            if title and self._current_href:
                url = f"https://s.weibo.com{self._current_href}"
                self.items.append({"title": title, "url": url})
            self._in_a = False
            self._current_href = None
            self._current_text = []
        elif tag == "td" and self._in_td_02:
            self._in_td_02 = False
        elif tag == "tr" and self._in_tr:
            self._in_tr = False
        elif tag == "tbody" and self._in_tbody:
            self._in_tbody = False
        elif tag == "table" and self._in_table:
            self._in_table = False


def _collect_weibo(limit: int) -> list:
    """微博实时热搜 - HTML 表格解析。"""
    url = "https://s.weibo.com/top/summary?cate=realtimehot"
    req = Request(url, headers={
        "User-Agent": UA,
        "Cookie": "SUB=_2AkMWIuNSf8NxqwJRmP8dy2rhaoV2ygrEieKgfhKJJRMxHRl-yT9jqk86tRB6PaLNvQZR6zYUcYVT1zSjoSreQHidcUq7",
        "Referer": url,
    }, method="GET")
    with urlopen(req, timeout=TIMEOUT) as resp:
        raw = resp.read().decode("utf-8", "replace")
    parser = WeiboTableParser()
    parser.feed(raw)
    return parser.items[:limit]


def _collect_hupu(limit: int) -> list:
    """虎扑热搜 - 正则表达式匹配。"""
    url = "https://bbs.hupu.com/topic-daily-hot"
    raw = _fetch(url)
    # 匹配 <li class="bbs-sl-web-post-body"> 中的 <a href="..." class="p-title">title</a>
    regex = re.compile(
        r'<li class="bbs-sl-web-post-body">[\s\S]*?'
        r'<a href="(/[^"]+?\.html)"[^>]*?class="p-title"[^>]*>([^<]+)</a>'
    )
    items = []
    for match in regex.finditer(raw):
        path, title = match.groups()
        if path and title:
            items.append({
                "title": title.strip(),
                "url": f"https://bbs.hupu.com{path}"
            })
            if len(items) >= limit:
                break
    return items


def _collect_aihot(limit: int) -> list:
    """AI Hot - JSON API 抓取。"""
    url = "https://aihot.virxact.com/api/public/items?mode=all&take=30"
    req = Request(url, headers={
        "User-Agent": f"{UA} aihot-skill/0.2.0 newsnow/0.0.40"
    }, method="GET")
    with urlopen(req, timeout=TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    items = []
    for item in data.get("items", [])[:limit]:
        title = item.get("title", "")
        link = item.get("url", "")
        if title and link:
            items.append({"title": title, "url": link})
    return items


def _collect_google_news(limit: int) -> list:
    """Google News 中文 - RSS 抓取。"""
    url = "https://news.google.com/rss?hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    try:
        raw = _fetch(url)
        # Google News RSS 含有 XML 声明，ET.fromstring 可以处理字符串
        root = ET.fromstring(raw)
        items = []
        for item in root.findall(".//item")[:limit]:
            title = item.find("title").text
            link = item.find("link").text
            if title and link:
                items.append({"title": title, "url": link})
        return items
    except Exception:
        return []


# 收集器函数映射表
_COLLECTORS = {
    "zhihu": _collect_zhihu,
    "douyin": _collect_douyin,
    "weibo": _collect_weibo,
    "hupu": _collect_hupu,
    "aihot": _collect_aihot,
    "google_news": _collect_google_news,
}


def collect_one(name: str, limit: int = LIMIT) -> list:
    """抓取单个源：自定义收集器 / 聚合通道 → 演示数据兜底。"""
    meta = next((m for m in SOURCE_META if m["name"] == name), None)
    if not meta:
        return []
    
    # 新增的 6 个源使用自定义收集器
    if "collector" in meta:
        collector_name = meta["collector"]
        collector_func = _COLLECTORS.get(collector_name)
        if collector_func:
            try:
                items = collector_func(limit)
                if items:
                    return items
            except (HTTPError, URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError):
                pass
        return _demo_items(name)
    
    # 原有的 12 个源使用聚合通道
    if "channel" in meta:
        try:
            items = _parse_channel(meta["channel"], meta["origin"], limit)
            if items:
                return items
        except (HTTPError, URLError, TimeoutError, ValueError):
            pass
    
    # 演示数据兜底
    return _demo_items(name)


def collect_all(limit: int = LIMIT) -> dict:
    """依次抓取全部 18 个源。返回 {name: [item, ...]}。"""
    result = {}
    for meta in SOURCE_META:
        cur_limit = limit
        if meta["name"] in ["抖音热搜", "微博实时热搜"]:
            cur_limit = 10
        result[meta["name"]] = collect_one(meta["name"], cur_limit)
    return result


# ---------------------------------------------------------------- 开篇 AI 总结引擎
# 换新方式：不再硬编码「AI 今天给你去噪音，留干货」开篇总结，改为对真实抓取到的标题做
# 「主题热度 + 多空情绪」统计，每次推送都随数据动态更新，零外部依赖、可离线运行。
# 如需接入在线大模型，只需覆盖 analyze_brief() 的返回值（字段保持一致即可）。

# (板块标签, 关键词)。一条标题命中任一关键词即计入该主题热度，并按数据源去重计权。
_THEMES = [
    ("AI 算力", ["AI", "人工智能", "算力", "大模型", "数据中心", "OpenAI", "Anthropic",
                "DeepMind", "GPT", "Claude", "Gemini", "Llama", "机器人", "GPU"]),
    ("光通信", ["光纤", "光通信", "光缆", "光模块", "古河电工"]),
    ("半导体", ["半导体", "芯片", "晶圆", "台积电", "英伟达", "AMD"]),
    ("贵金属", ["黄金", "铂金", "钯金", "白银", "原油", "稀土", "矿产"]),
    ("美联储", ["美联储", "央行", "加息", "降息", "货币政策", "贝森特", "日元", "汇率",
               "美元", "逆回购", "流动性", "利率"]),
    ("地缘", ["伊朗", "阿曼", "霍尔木兹", "海峡", "中东", "战争", "制裁", "美伊",
             "特朗普", "干预"]),
    ("医药", ["诺和诺德", "医药", "医疗", "GLP", "疫苗", "制药", "临床", "辉瑞"]),
    ("智驾", ["自动驾驶", "智驾", "智能驾驶", "新能源车", "特斯拉", "L3", "L4"]),
    ("地产", ["楼市", "地产", "房价", "房企", "豪宅"]),
    ("消费", ["消费", "零售", "电商", "餐饮", "麦当劳", "宝洁", "亚马逊"]),
    ("航天", ["SpaceX", "火箭", "卫星", "发射"]),
]

_BULLISH = ["上涨", "暴涨", "大涨", "涨超", "涨逾", "涨幅扩大", "创新高", "新高", "首破",
            "突破", "上调", "增持", "利好", "扩产", "反弹", "回升", "盈利", "超预期",
            "开门红", "修复", "反攻", "暴增", "回暖", "翻倍", "前景改善", "净利", "企稳"]
_BEARISH = ["下跌", "暴跌", "重挫", "新低", "危机", "风险", "警示", "警惕", "债务", "逾期",
            "诉讼", "立案", "下调", "减持", "冲击", "利空", "泡沫", "争议", "放缓", "衰退",
            "疲软", "贬值", "缩水", "承压", "亏损", "负增长", "暴雷", "抛售"]


def analyze_brief(brief: dict) -> dict:
    """对采集结果做本地「AI 总结」：主题热度 + 多空博弈概率 + 板块风向 + 资金流向。

    返回：
        headline      「AI 今天给你去噪音，留干货」正文（纯文本，引用热度最高的一两个板块）
        bias          偏多 / 偏空 / 中性
        bull          多方概率（百分比整数）
        bear          空方概率（百分比整数）
        sectors       热度最高的板块标签列表（最多 2 个）
        top_themes    全部命中主题 [(标签, 跨源数, 提及数)]，按信号强度排序
        sectors_up    利好板块（多头信号占优的主题，最多 3 个）
        sectors_down  利差板块（空头信号占优的主题，最多 2 个，可能为空）
        flow          资金流向分析句（纯文本）
        points        开篇四个观点 [{key, label, text}]：
                      1 市场情绪 2 多空博弈概率 3 利好/利差板块 4 资金流向分析
    """
    theme_sources = {tag: set() for tag, _ in _THEMES}
    theme_mentions = {tag: 0 for tag in theme_sources}
    # 按主题累计多/空信号：只有方向明确的标题才计入对应主题的多空账。
    theme_up = {tag: 0 for tag in theme_sources}
    theme_down = {tag: 0 for tag in theme_sources}
    bull = bear = 0

    for name, items in (brief or {}).items():
        for item in items or []:
            title = item.get("title", "") or ""
            if not title:
                continue
            # 多空：单条标题按「多方词命中数 vs 空方词命中数」判定方向，避免单条重复计数。
            up = sum(1 for word in _BULLISH if word in title)
            down = sum(1 for word in _BEARISH if word in title)
            if up > down:
                bull += 1
                direction = 1
            elif down > up:
                bear += 1
                direction = -1
            else:
                direction = 0
            # 主题：命中即累计，并记录出现在哪些数据源（跨源命中 = 更强信号）。
            for tag, keywords in _THEMES:
                if any(keyword in title for keyword in keywords):
                    theme_mentions[tag] += 1
                    theme_sources[tag].add(name)
                    if direction > 0:
                        theme_up[tag] += 1
                    elif direction < 0:
                        theme_down[tag] += 1

    ranked = sorted(
        ((tag, len(theme_sources[tag]), theme_mentions[tag]) for tag in theme_sources),
        key=lambda entry: (entry[1], entry[2]),
        reverse=True,
    )
    top_themes = [(tag, src, men) for tag, src, men in ranked if src > 0]
    sectors = [tag for tag, _, _ in top_themes[:2]]

    if bull + bear > 0:
        bull_pct = round(bull / (bull + bear) * 100)
        bear_pct = 100 - bull_pct
        if bull_pct >= 60:
            bias = "偏多"
        elif bull_pct <= 40:
            bias = "偏空"
        else:
            bias = "中性"
    else:
        # 无任何多空信号（例如空简报）：诚实标注中性，不做无依据的方向判断。
        bull_pct, bear_pct, bias = 50, 50, "中性"

    # 利好 / 利差板块：净多头（净空头）信号 > 0 的主题，按信号强度与热度排序。
    sectors_up = [
        tag for tag, _, _ in sorted(
            ((tag, len(theme_sources[tag]), theme_mentions[tag]) for tag in theme_sources
             if theme_up[tag] > theme_down[tag]),
            key=lambda entry: (theme_up[entry[0]] - theme_down[entry[0]], entry[1], entry[2]),
            reverse=True,
        )[:3]
    ]
    sectors_down = [
        tag for tag, _, _ in sorted(
            ((tag, len(theme_sources[tag]), theme_mentions[tag]) for tag in theme_sources
             if theme_down[tag] > theme_up[tag]),
            key=lambda entry: (theme_down[entry[0]] - theme_up[entry[0]], entry[1], entry[2]),
            reverse=True,
        )[:2]
    ]

    headline = _compose_headline(bias, top_themes)
    flow = _compose_flow(sectors_up, sectors_down, top_themes)
    points = [
        {"key": "sentiment", "label": "市场情绪",
         "text": _compose_sentiment(bias, bull_pct, bear_pct)},
        {"key": "battle", "label": "多空博弈概率",
         "text": _compose_battle(bias, bull_pct, bear_pct, bull + bear)},
        {"key": "sectors", "label": "利好 / 利差板块",
         "text": _compose_sectors(sectors_up, sectors_down)},
        {"key": "flow", "label": "资金流向分析", "text": flow},
    ]
    return {
        "headline": headline,
        "bias": bias,
        "bull": bull_pct,
        "bear": bear_pct,
        "sectors": sectors,
        "top_themes": top_themes,
        "sectors_up": sectors_up,
        "sectors_down": sectors_down,
        "flow": flow,
        "points": points,
    }


def _compose_headline(bias: str, top_themes: list) -> str:
    """依据多空方向与热度最高的板块，拼出自然的「AI 今天给你去噪音，留干货」总结句。"""
    t1 = top_themes[0][0] if top_themes else None
    t2 = top_themes[1][0] if len(top_themes) > 1 else None

    if bias == "偏多":
        if t1 and t2:
            return f"市场风险偏好回升，资金聚焦{t1}与{t2}两条线索，多方情绪占优，但短期需警惕高位分化。"
        if t1:
            return f"市场情绪偏暖，{t1}成为资金聚焦主线，多方占优，注意高位波动。"
        return "市场情绪偏暖，多方占优，但热点轮动较快，注意追高风险。"
    if bias == "偏空":
        if t1 and t2:
            return f"市场情绪转弱，{t1}与{t2}扰动增多，避险情绪升温，短期宜控制仓位。"
        if t1:
            return f"市场情绪转弱，{t1}风险扰动增多，空方占优，宜谨慎应对。"
        return "市场情绪偏谨慎，空方占优，风险事件增多，短期以防御为主。"
    if t1 and t2:
        return f"市场分歧加大，{t1}与{t2}轮动频繁，多空力量接近，方向尚待明朗。"
    if t1:
        return f"市场方向未明，{t1}成为焦点但分歧较大，等待更多信号确认。"
    return "市场多空拉锯，方向尚不明朗，建议控制仓位、等待信号。"


def _compose_sentiment(bias: str, bull_pct: int, bear_pct: int) -> str:
    """观点 1：今天市场情绪——由多空占比与方向拼出情绪描述。"""
    if bias == "偏多":
        mood = "情绪明显乐观" if bull_pct >= 70 else "情绪偏暖，多方占上风"
        return f"{mood}，风险偏好回升，但需留意高位轮动分化。"
    if bias == "偏空":
        mood = "避险情绪主导" if bear_pct >= 70 else "情绪偏谨慎"
        return f"{mood}，风险扰动增多，短线以防御为主。"
    return "多空分歧较大，观望情绪浓，方向选择临近，跟随信号为宜。"


def _compose_battle(bias: str, bull_pct: int, bear_pct: int, signals: int) -> str:
    """观点 2：多空博弈概率——百分比 + 胶着/占优判断 + 样本量。"""
    if signals <= 0:
        return "暂无可统计的多空信号，按 50% : 50% 中性看待，等待新数据。"
    if bull_pct >= 60:
        verdict = "多方明显占优"
    elif bull_pct <= 40:
        verdict = "空方略占上风"
    else:
        verdict = "多空胶着，差距有限"
    return f"多方 {bull_pct}% : 空方 {bear_pct}%，{verdict}（基于 {signals} 条多空信号）。"


def _compose_sectors(sectors_up: list, sectors_down: list) -> str:
    """观点 3：利好板块 / 利差板块——净多、净空信号各自排序取头部。"""
    up_text = "、".join(sectors_up) if sectors_up else "暂无明确主线，多头信号分散"
    down_text = "、".join(sectors_down) if sectors_down else "暂无明显承压板块"
    return f"利好板块：{up_text}　|　利差板块：{down_text}。"


def _compose_flow(sectors_up: list, sectors_down: list, top_themes: list) -> str:
    """观点 4：资金流向分析——净流入看利好板块，回避方向看利差板块。"""
    parts = []
    if sectors_up:
        parts.append(f"资金净流入集中在{'、'.join(sectors_up)}")
    if sectors_down:
        parts.append(f"{'、'.join(sectors_down)}相关资产遭资金回避")
    if parts:
        return "；".join(parts) + "。"
    hot = [tag for tag, _, _ in top_themes[:2]]
    if hot:
        return f"资金目光聚焦{'、'.join(hot)}，但方向性流入尚不明确，轮动观望为主。"
    return "样本有限，资金流向暂不明朗，建议等待更多信号确认。"


# ---------------------------------------------------------------- 最新 A 股复盘引擎
# 「AI 复盘 · 最新 A 股」板块：按六维度内容策略，用 AI 视角复盘最新的 A 股行情——
#   ① 三大指数涨跌　② 两市成交额　③ 涨跌家数与涨跌停　④ 领涨/领跌板块
#   ⑤ 主力资金与北向资金　⑥ 后市观点与策略
# 数据链路与 18 个新闻源一致：东方财富公开行情接口（主源，指数日 K、涨停/跌停池均支持
# 按日回溯）优先抓取 → 腾讯证券行情接口（备用源，指数日 K）补位 → 内置真实快照
# （2026-08-27 收盘数据）兜底，任何环境都能稳定出内容。
# 说明：北向资金实时数据自 2024 年 8 月起已停止披露，复盘口径改为主力资金 + 两融。

_ASHARE_UT = "fa5fd1943c7b386f172d6893dbfba10b"
_ASHARE_INDICES = [
    ("上证指数", "1.000001"),   # 沪市成交额计入两市口径
    ("深证成指", "0.399001"),   # 深市成交额计入两市口径
    ("创业板指", "0.399006"),
    ("科创50", "1.000688"),
]
_ASHARE_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
_ASHARE_ZT_URL = "https://push2ex.eastmoney.com/getTopicZTPool"
_ASHARE_DT_URL = "https://push2ex.eastmoney.com/getTopicDTPool"
_ASHARE_TIMEOUT = 6

# 备用行情源：腾讯证券公开日 K 接口（主源东方财富失联/缺指数时自动补位）。
# 返回字段仅 日期/开/收/高/低/量，无成交额；涨跌额与涨跌幅由相邻两日收盘价推算。
_ASHARE_TX_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
_ASHARE_TX_SYMBOLS = [
    ("上证指数", "sh000001"),
    ("深证成指", "sz399001"),
    ("创业板指", "sz399006"),
    ("科创50", "sh000688"),
]

# 新鲜度闸门认可的实时行情来源（内置快照 snapshot 不在其列）。
_ASHARE_LIVE_SOURCES = {
    "eastmoney": "东方财富实时行情接口",
    "tencent": "腾讯证券备用行情接口",
}

# 内置真实快照：2026-08-27（周四）A 股收盘行情。
# 数据来源：东方财富日 K/涨停池接口实测，与新浪财经、每日经济新闻、财联社当日收评交叉核对一致
# （两市 2.13 万亿、放量 3172 亿、涨停 77 家 / 跌停 3 家等口径全部对上）。
_ASHARE_SNAPSHOT = {
    "date": "2026-08-28",
    "source": "snapshot",
    "indices": [
        {"name": "上证指数", "close": 3956.57, "pct": 1.13, "change": 44.05},
        {"name": "深证成指", "close": 14048.88, "pct": 1.50, "change": 207.55},
        {"name": "创业板指", "close": 3473.35, "pct": 1.71, "change": 58.47},
        {"name": "科创50", "close": 1693.48, "pct": 3.77, "change": 61.46},
    ],
    "turnover": {"amount": 21259, "prev": 18087, "delta": 3172, "unit": "亿"},
    "breadth": {
        "up_text": "超3300只",
        "limit_up": 77, "limit_down": 3,
        "broken": 17, "seal_rate": "82%",
        "ladder": "深中华A 6 连板，金健米业 9 天 6 板",
        "hot_sectors": ["算力硬件", "存储芯片", "农业", "黄金"],
    },
    "leaders": [
        {"name": "算力硬件", "note": "CPO/PCB/光纤齐涨，赛微电子20cm涨停、长飞光纤涨停"},
        {"name": "存储芯片", "note": "大普微20cm涨停，澜起科技涨超10%"},
        {"name": "农业", "note": "新赛股份、万向德农等涨停"},
        {"name": "黄金", "note": "湖南黄金、莱绅通灵涨停"},
    ],
    "laggards": [
        {"name": "银行", "note": "浙商银行领跌"},
        {"name": "白酒", "note": "洋河股份领跌"},
        {"name": "电网设备", "note": "思源电气跌停"},
    ],
    "funds": {
        "main": "机构与主力资金早盘起持续净流入，主攻半导体、算力硬件、存储芯片等科技方向",
        "north": "北向资金实时数据自 2024 年 8 月起停止披露，以主力资金与两融口径观察",
    },
    "outlook": {
        "views": [
            "浙商证券：缩量地量后未来 1-2 周是关键变盘窗口，方向边际偏乐观，9 月科技仍是核心主线",
            "盘面：沪指 3 连阳剑指 60 日线，科创50 突破半年线，价升量增、增量资金入场",
        ],
        "catalyst": "英伟达财报超预期（营收 +106%）并披露联合 AWS 部署 200 万块 GPU；国家统计局：1-7 月集成电路行业利润同比 +18.5 倍",
    },
}


def _ashare_today() -> "datetime.date":
    """北京时间今天（GitHub Actions 使用 UTC 运行，需要 +8 小时）。"""
    return (datetime.now(timezone.utc) + timedelta(hours=8)).date()


def _parse_ashare_candle(line: str) -> dict | None:
    """东方财富日 K 一行 → 字典。格式：date,open,close,high,low,volume,amount,振幅,pct,change,换手率。"""
    parts = (line or "").split(",")
    if len(parts) < 11:
        return None
    try:
        return {
            "date": parts[0],
            "close": float(parts[2]),
            "amount": float(parts[6]),  # 单位：元
            "pct": float(parts[8]),
            "change": float(parts[9]),
            "source": "eastmoney",
        }
    except ValueError:
        return None


def _parse_tencent_candle(row, prev_close: float | None) -> dict | None:
    """腾讯证券日 K 一行 → 字典。行格式：[date, open, close, high, low, volume, ...]。

    接口不含成交额与涨跌幅：amount 置 None（两市成交额降级为不展示），
    涨跌额/涨跌幅由前一日收盘价推算（首行无前收，由调用方丢弃）。
    """
    if not isinstance(row, (list, tuple)) or len(row) < 6:
        return None
    try:
        close = float(row[2])
    except (TypeError, ValueError):
        return None
    date = str(row[0])
    if prev_close is None or prev_close <= 0:
        change = pct = None
    else:
        change = round(close - prev_close, 2)
        pct = round(change / prev_close * 100, 2)
    return {
        "date": date,
        "close": close,
        "amount": None,  # 腾讯日 K 无成交额字段
        "pct": pct,
        "change": change,
        "source": "tencent",
    }



def _fetch_json(url: str, params: dict) -> dict:
    """GET 公开接口并解析 JSON（UA 伪装 + 短超时，任何异常向上抛由调用方兜底）。"""
    request = Request(f"{url}?{urlencode(params)}", headers={"User-Agent": UA})
    with urlopen(request, timeout=_ASHARE_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def _fetch_ashare_klines_eastmoney() -> dict:
    """主源（东方财富）：四个指数最近 16 根日 K（含成交额）。返回 {指数名: {date: candle}}，个别失败跳过。"""
    result = {}
    for name, secid in _ASHARE_INDICES:
        try:
            payload = _fetch_json(_ASHARE_KLINE_URL, {
                "ut": _ASHARE_UT, "secid": secid, "klt": 101, "fqt": 0,
                "end": "20500101", "lmt": 16,
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            })
            klines = ((payload.get("data") or {}).get("klines")) or []
            candles = {}
            for line in klines:
                candle = _parse_ashare_candle(line)
                if candle:
                    candles[candle["date"]] = candle
            if candles:
                result[name] = candles
        except Exception:
            continue
    return result


def _fetch_ashare_klines_tencent() -> dict:
    """备用源（腾讯证券）：四个指数最近 16 根日 K。返回 {指数名: {date: candle}}，个别失败跳过。

    多抓一根（17）用于推算首日涨跌幅后丢弃，保证返回的 16 根都有 pct/change。
    """
    result = {}
    for name, symbol in _ASHARE_TX_SYMBOLS:
        try:
            payload = _fetch_json(_ASHARE_TX_KLINE_URL, {"param": f"{symbol},day,,,17,qfq"})
            data = ((payload.get("data") or {}).get(symbol)) or {}
            rows = data.get("day") or data.get("qfqday") or []
            candles = {}
            prev_close = None
            for row in rows:
                candle = _parse_tencent_candle(row, prev_close)
                if not candle:
                    continue
                prev_close = candle["close"]
                if candle["pct"] is None:  # 首行无前收，仅用于校准，不入结果
                    continue
                candles[candle["date"]] = candle
            if candles:
                result[name] = candles
        except Exception:
            continue
    return result


def _fetch_ashare_klines() -> dict:
    """抓取四大指数日 K：东方财富（主）优先，缺指数/失联时用腾讯证券（备）补位。"""
    klines = _fetch_ashare_klines_eastmoney()
    if len(klines) < len(_ASHARE_INDICES):
        try:
            backup = _fetch_ashare_klines_tencent()
        except Exception:
            backup = {}
        for name, candles in backup.items():
            klines.setdefault(name, candles)
    return klines


def _pick_review_date(klines: dict, today) -> str | None:
    """最新 A 股复盘日：≤ 今天的最近一个交易日（最新日 K，周末/长假自动向前回溯）。"""
    target = str(today)
    dates = sorted({d for candles in klines.values() for d in candles}, reverse=True)
    for date in dates:
        if date <= target:
            return date
    return dates[0] if dates else None


def _get_fallback_review_date(today=None) -> str:
    """基于『今天』推导的最新 A 股复盘交易日（≤ 今天的最近交易日，离线/兜底时使用）。"""
    if today is None:
        today = _ashare_today()
    target = today
    while target.weekday() >= 5:
        target -= timedelta(days=1)
    return str(target)


def _fetch_ashare_pools(review_date: str) -> dict:
    """涨停/跌停池（按日回溯）：家数 + 涨停行业分布（领涨线索）+ 跌停行业分布（领跌线索）。"""
    out = {"limit_up": None, "limit_down": None, "hot_sectors": [], "cold_sectors": []}
    ymd = review_date.replace("-", "")

    def _sector_counts(data: dict, key: str) -> list:
        counts = {}
        for stock in (data or {}).get("pool") or []:
            sector = stock.get("hybk") or ""
            if sector:
                counts[sector] = counts.get(sector, 0) + 1
        return sorted(counts, key=counts.get, reverse=True)

    try:
        zt = _fetch_json(_ASHARE_ZT_URL, {
            "ut": "7eea3edcaed734bea9cbfc24409ed989", "dpt": "wz.ztzt",
            "Pageindex": 0, "pagesize": 5, "sort": "fbt:asc", "date": ymd,
        })
        data = zt.get("data") or {}
        out["limit_up"] = data.get("tc")
        out["hot_sectors"] = _sector_counts(data, "zt")[:4]
    except Exception:
        pass
    try:
        dt = _fetch_json(_ASHARE_DT_URL, {
            "ut": "7eea3edcaed734bea9cbfc24409ed989", "dpt": "wz.ztzt",
            "Pageindex": 0, "pagesize": 5, "sort": "fund:asc", "date": ymd,
        })
        data = dt.get("data") or {}
        out["limit_down"] = data.get("tc")
        out["cold_sectors"] = _sector_counts(data, "dt")[:3]
    except Exception:
        pass
    return out


def get_ashare_market() -> dict:
    """采集最新 A 股行情：东方财富接口优先 → 腾讯证券备用接口补位，全部失败回退内置真实快照。"""
    return _build_ashare_market(_fetch_ashare_klines(), _ashare_today())


def _build_ashare_market(klines: dict, today) -> dict:
    """由已抓取的日 K 组装最新复盘行情（东方财富 → 内置快照兜底）。

    与网络解耦：日 K 由调用方传入（`get_ashare_market()` 抓一次网络，
    `collect_market_for_push()` 复用同一次结果做新鲜度检查），便于测试注入。
    """
    fallback_date = _get_fallback_review_date(today)
    try:
        review_date = _pick_review_date(klines, today)
        if not review_date:
            snapshot = dict(_ASHARE_SNAPSHOT)
            snapshot["date"] = fallback_date
            return snapshot

        indices = []
        market_source = None
        for name, _secid in _ASHARE_INDICES:
            candle = (klines.get(name) or {}).get(review_date)
            if candle:
                if market_source is None:
                    market_source = candle.get("source") or "eastmoney"
                indices.append({
                    "name": name,
                    "close": candle["close"],
                    "pct": candle["pct"],
                    "change": candle["change"],
                })
        if len(indices) < 3:
            snapshot = dict(_ASHARE_SNAPSHOT)
            snapshot["date"] = fallback_date
            return snapshot

        # 两市成交额：沪市（上证）+ 深市（深成）日 K 的成交额（单位：元 → 亿元）。
        # 备用源（腾讯）无成交额字段（amount=None）时该维度自动降级为不展示。
        sh = (klines.get("上证指数") or {}).get(review_date)
        sz = (klines.get("深证成指") or {}).get(review_date)
        turnover = None
        if sh and sz and sh.get("amount") is not None and sz.get("amount") is not None:
            amount = (sh["amount"] + sz["amount"]) / 1e8
            prev_date = next(
                (d for d in sorted((klines.get("上证指数") or {}), reverse=True) if d < review_date),
                None,
            )
            delta = None
            if prev_date:
                psh = (klines.get("上证指数") or {}).get(prev_date)
                psz = (klines.get("深证成指") or {}).get(prev_date)
                if psh and psz and psh.get("amount") is not None and psz.get("amount") is not None:
                    delta = round(amount - (psh["amount"] + psz["amount"]) / 1e8)
            turnover = {"amount": round(amount), "delta": delta, "unit": "亿"}

        pools = _fetch_ashare_pools(review_date)
        leaders = [{"name": s, "note": "涨停家数居前"} for s in pools["hot_sectors"]]
        laggards = [{"name": s, "note": "跌停个股所在"} for s in pools["cold_sectors"]]
        return {
            "date": review_date,
            "source": market_source or "eastmoney",
            "indices": indices,
            "turnover": turnover,
            "breadth": {
                "up_text": None,
                "limit_up": pools["limit_up"], "limit_down": pools["limit_down"],
                "broken": None, "seal_rate": None, "ladder": None,
                "hot_sectors": pools["hot_sectors"],
            },
            "leaders": leaders,
            "laggards": laggards,
            "funds": {
                "main": None,
                "north": "北向资金实时数据自 2024 年 8 月起停止披露，以主力资金与两融口径观察",
            },
            "outlook": {"views": [], "catalyst": None},
        }
    except Exception:
        snapshot = dict(_ASHARE_SNAPSHOT)
        snapshot["date"] = fallback_date
        return snapshot


# ---------------------------------------------------------------- 大盘数据新鲜度闸门
# 推送前检查：简报里的「大盘数据」必须是最新的，不是最新就不推。
# 判定标准（三条全过才算「最新」）：
#   ① 行情接口可用——主源（东方财富）与备用源（腾讯证券）都拿不到日 K 就无法确认
#      数据新旧，宁可不放行；
#   ② 接口数据不滞后——最新日 K 不得早于内置快照基线日期（日期只会向前走，
#      一旦倒退说明行情源异常）；
#   ③ 大盘复盘数据来自实时接口（东方财富或腾讯证券备用源，非内置快照兜底），
#      且复盘日 = 按最新口径应复盘的最近交易日（接口数据自动覆盖周末/长假回溯）。

def check_market_freshness(market: dict | None = None,
                           klines: dict | None = None,
                           today=None) -> dict:
    """检查大盘复盘数据是否为最新。返回：

        ok                是否最新（推送闸门以此为据）
        reason            人类可读结论（含具体日期，可直接进日志/推送提示）
        market_date       本次大盘复盘数据的日期
        source            数据来源（eastmoney 主接口 / tencent 备用接口 / snapshot 内置快照）
        latest_kline_date 行情接口最新一根日 K 的日期（接口视角的“今天”）
        expected_date     按最新口径应复盘的最近交易日
        checked_at        检查时间（北京时间）
    """
    today = today or _ashare_today()
    if klines is None:
        klines = _fetch_ashare_klines()
    if market is None:
        market = _build_ashare_market(klines, today)

    dates = sorted({d for candles in klines.values() for d in candles}, reverse=True)
    info = {
        "ok": False,
        "reason": "",
        "market_date": market.get("date") or "",
        "source": market.get("source") or "snapshot",
        "latest_kline_date": dates[0] if dates else "",
        "expected_date": "",
        "checked_at": (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S"),
    }

    if not dates:
        info["reason"] = ("行情接口不可用（主源东方财富与备用源腾讯证券均未返回日 K），"
                          "无法确认大盘数据为最新"
                          f"（当前兜底：内置快照，复盘日 {info['market_date'] or '未知'}）")
        return info

    expected = _pick_review_date(klines, today)
    info["expected_date"] = expected or ""
    floor = _ASHARE_SNAPSHOT["date"]  # 已知基线：接口最新日 K 不可能早于内置快照日期

    if dates[0] < floor:
        info["reason"] = (f"行情接口数据滞后：最新日 K {dates[0]} 早于内置快照基线 {floor}"
                          "，判定非最新")
        return info
    if market.get("source") not in _ASHARE_LIVE_SOURCES:
        info["reason"] = (f"大盘数据回退内置快照（冻结于 {floor}），非实时接口数据，"
                          f"无法确认为最新（应复盘交易日 {expected or '未知'}）")
        return info
    if not expected or market.get("date") != expected:
        info["reason"] = (f"大盘复盘日 {info['market_date'] or '未知'} 与最新可复盘交易日 "
                          f"{expected or '未知'} 不一致，判定非最新")
        return info

    info["ok"] = True
    source_label = _ASHARE_LIVE_SOURCES.get(market.get("source"), "实时行情接口")
    info["reason"] = f"大盘数据为最新：复盘交易日 {expected}（数据来源：{source_label}）"
    return info


def collect_market_for_push() -> tuple[dict, dict]:
    """推送入口专用：一次抓取完成「大盘数据 + 新鲜度检查」。

    返回 (market, freshness)：market 供 analyze_ashare() 渲染复盘板块，
    freshness 供推送闸门判定「不是最新就不推」。日 K 只抓一次，两处共用。

    环境变量 MARKET_FRESHNESS_FORCE=fresh|stale 可强制检查结果（测试/应急用，
    正常推送不要设置）。
    """
    today = _ashare_today()
    klines = _fetch_ashare_klines()
    market = _build_ashare_market(klines, today)
    freshness = check_market_freshness(market, klines=klines, today=today)

    force = os.environ.get("MARKET_FRESHNESS_FORCE", "").strip().lower()
    if force in ("fresh", "stale"):
        freshness["forced"] = True
        freshness["ok"] = force == "fresh"
        freshness["reason"] = f"MARKET_FRESHNESS_FORCE={force} 强制结果（测试/应急）：" + freshness["reason"]
    return market, freshness


def _ashare_bias(market: dict) -> str:
    """由指数涨跌、量能与涨停/跌停对比综合打分，给出偏多/偏空/中性。"""
    indices = market.get("indices") or []
    pcts = [i["pct"] for i in indices]
    avg = sum(pcts) / len(pcts) if pcts else 0
    breadth = market.get("breadth") or {}
    lu, ld = breadth.get("limit_up"), breadth.get("limit_down")
    delta = (market.get("turnover") or {}).get("delta")

    score = avg * 0.6
    if isinstance(delta, (int, float)):
        score += 1 if delta > 0 else -1
    if isinstance(lu, int) and isinstance(ld, int):
        score += 1 if lu > ld * 3 else (-0.5 if lu < ld else 0.3)
    if sum(1 for i in indices if i["pct"] > 0) >= 3:
        score += 0.6
    if score >= 1.2:
        return "偏多"
    if score <= -0.6:
        return "偏空"
    return "中性"


def _fmt_amt(amount: float) -> str:
    """亿元 → 万亿/亿 展示。"""
    return f"{amount / 10000:.2f} 万亿" if amount >= 10000 else f"{amount:,.0f} 亿"


def _compose_ashare_headline(market: dict, bias: str) -> str:
    """AI 一句话复盘：方向 + 领涨主线 + 最强指数 + 风险提示。"""
    leaders = [n["name"] for n in (market.get("leaders") or [])][:2]
    indices = market.get("indices") or []
    best = max(indices, key=lambda i: i["pct"], default=None)
    delta = (market.get("turnover") or {}).get("delta") or 0
    lu = (market.get("breadth") or {}).get("limit_up")

    if bias == "偏多":
        tone = "放量普涨" if delta > 0 else "企稳反弹"
    elif bias == "偏空":
        tone = "承压回落"
    else:
        tone = "震荡分化"
    parts = [tone]
    if leaders:
        parts.append(f"{'与'.join(leaders)}领涨主线")
    if best and best["pct"] > 0:
        parts.append(f"{best['name']} {best['pct']:+.2f}% 领跑")
    if isinstance(lu, int):
        parts.append(f"涨停 {lu} 家")
    if bias == "偏多":
        parts.append("短线情绪偏暖，注意高位轮动")
    elif bias == "偏空":
        parts.append("避险情绪升温，控制仓位")
    else:
        parts.append("方向待确认，低吸不追高")
    return "，".join(parts) + "。"


def _compose_ashare_indices(indices: list) -> str:
    """维度 ① 三大指数涨跌：指数明细 + 格局判断。"""
    if not indices:
        return "指数数据暂缺，以当日盘面为准。"
    items = [f"{i['name']} {i['pct']:+.2f}%（报 {i['close']:.2f} 点）" for i in indices]
    up = sum(1 for i in indices if i["pct"] > 0)
    down = sum(1 for i in indices if i["pct"] < 0)
    if up == len(indices):
        verdict = "主要指数集体收涨，呈普涨格局"
    elif down == len(indices):
        verdict = "指数全线收跌，防御情绪升温"
    else:
        verdict = "指数涨跌分化，结构行情为主"
    best = max(indices, key=lambda i: i["pct"], default=None)
    if best and best["pct"] >= 2 and up > down:
        verdict += f"，{best['name']} 领跑、成长风格占优"
    return "、".join(items) + "。" + verdict + "。"


def _compose_ashare_turnover(turnover: dict | None) -> str:
    """维度 ② 两市成交额：量能水平 + 放量/缩量解读。"""
    if not turnover or turnover.get("amount") is None:
        return "成交额数据暂缺。"
    amount = turnover["amount"]
    text = f"沪深两市成交 {_fmt_amt(amount)}"
    delta = turnover.get("delta")
    if delta is None and turnover.get("prev") is not None:
        delta = amount - turnover["prev"]
    if isinstance(delta, (int, float)) and delta != 0:
        base = amount - delta
        pct = abs(delta) / base * 100 if base > 0 else 0
        if delta > 0:
            text += f"，较前一日放量 {_fmt_amt(delta)}（+{pct:.1f}%），量价齐升、增量资金入场信号明确"
        else:
            text += f"，较前一日缩量 {_fmt_amt(-delta)}（-{pct:.1f}%），观望情绪仍待消化"
    return text + "。"


def _compose_ashare_breadth(breadth: dict | None) -> str:
    """维度 ③ 涨跌家数与涨跌停：市场广度 + 连板梯队 + 情绪温度。"""
    b = breadth or {}
    parts = []
    if b.get("up_text"):
        parts.append(f"全市场{b['up_text']}个股上涨")
    if isinstance(b.get("limit_up"), int):
        parts.append(f"涨停 {b['limit_up']} 家")
    if isinstance(b.get("limit_down"), int):
        parts.append(f"跌停 {b['limit_down']} 家")
    if b.get("broken"):
        parts.append(f"炸板 {b['broken']} 家、封板率 {b['seal_rate'] or '—'}")
    if b.get("ladder"):
        parts.append(f"连板高度：{b['ladder']}")
    if not parts:
        return "涨跌家数盘后口径暂缺，以涨停/跌停与指数方向综合判断。"
    text = "、".join(parts)
    lu, ld = b.get("limit_up"), b.get("limit_down")
    if isinstance(lu, int) and isinstance(ld, int):
        if lu > ld * 3:
            text += "，赚钱效应与短线情绪偏暖"
        elif ld > lu:
            text += "，亏钱效应显现、情绪偏弱"
    return text + "。"


def _compose_ashare_sectors(market: dict) -> str:
    """维度 ④ 领涨/领跌板块：主线 + 退潮方向 + 点评。"""
    leaders = market.get("leaders") or []
    laggards = market.get("laggards") or []
    if not leaders and not laggards:
        hot = (market.get("breadth") or {}).get("hot_sectors") or []
        if hot:
            return f"涨停梯队集中在{'、'.join(hot)}，主线延续性待验证。"
        return "板块线索暂缺，等待盘后行业数据。"
    text = f"领涨：{'、'.join(n['name'] for n in leaders[:4])}"
    if leaders and leaders[0].get("note"):
        text += f"（{leaders[0]['note']}）"
    if laggards:
        text += f"；领跌：{'、'.join(n['name'] for n in laggards[:3])}"
        if laggards[0].get("note"):
            text += f"（{laggards[0]['note']}）"
    if leaders and laggards:
        tech_keys = ("科技", "算力", "半导体", "芯片", "存储", "电子", "通信", "计算机", "CPO", "PCB")
        leader_text = "".join(n["name"] for n in leaders)
        closer = ("科技硬主线扩散、防御与高位消费遭资金抽离"
                  if any(k in leader_text for k in tech_keys)
                  else "热点高低切换、结构性轮动延续")
        text += f"。{closer}"
    return text + "。"


def _compose_ashare_funds(market: dict) -> str:
    """维度 ⑤ 主力资金与北向资金：流入主线 + 北向口径说明。"""
    f = market.get("funds") or {}
    parts = [p for p in (f.get("main"), f.get("north")) if p]
    if not f.get("main"):
        # 实时路径无盘后主力资金明细：用涨停梯队行业分布作为封板资金线索。
        hot = (market.get("breadth") or {}).get("hot_sectors") or []
        if hot:
            parts.insert(0, f"涨停梯队集中在{'、'.join(hot)}（封板资金口径），主力资金盘后明细待更新")
    if not parts:
        return "资金口径数据暂缺，以主力资金与两融数据为准。"
    return "；".join(parts) + "。"


def _compose_ashare_outlook(market: dict, bias: str) -> str:
    """维度 ⑥ 后市观点与策略：AI 研判 + 催化 + 机构观点。"""
    if bias == "偏多":
        verdict = "短线偏多但防高位轮动：量能若能维持，可沿领涨主线低吸参与，避免追高连板高位股"
    elif bias == "偏空":
        verdict = "短线以防御为主：控制仓位，等待跌停收敛与量能企稳信号"
    else:
        verdict = "方向未明：控制仓位、低吸不追高，等待变盘信号"
    outlook = market.get("outlook") or {}
    text = f"AI 研判：{verdict}"
    if outlook.get("catalyst"):
        text += f"；催化：{outlook['catalyst']}"
    if outlook.get("views"):
        text += "；机构观点：" + "；".join(outlook["views"])
    return text + "。"


def analyze_ashare(market: dict | None = None) -> dict:
    """最新 A 股六维度 AI 复盘。``market`` 缺省时先尝试实时采集，失败回退内置快照。

    返回：
        date       复盘交易日（如 2026-08-27）
        source     数据来源（eastmoney 主接口 / tencent 备用接口 / snapshot 内置快照）
        headline   AI 一句话复盘
        bias       偏多 / 偏空 / 中性
        indices    四大指数明细 [{name, close, pct, change}]
        leaders    领涨板块 [{name, note}]；laggards 领跌板块
        turnover   成交额 {amount 亿, delta 亿, unit}
        breadth    涨跌家数/涨跌停/连板信息
        points     六维度观点 [{key, label, text}]
    """
    market = market if market is not None else get_ashare_market()
    bias = _ashare_bias(market)
    points = [
        {"key": "indices", "label": "三大指数",
         "text": _compose_ashare_indices(market.get("indices") or [])},
        {"key": "turnover", "label": "两市成交额",
         "text": _compose_ashare_turnover(market.get("turnover"))},
        {"key": "breadth", "label": "涨跌家数与涨跌停",
         "text": _compose_ashare_breadth(market.get("breadth"))},
        {"key": "sectors", "label": "领涨 / 领跌板块",
         "text": _compose_ashare_sectors(market)},
        {"key": "funds", "label": "主力资金与北向资金",
         "text": _compose_ashare_funds(market)},
        {"key": "outlook", "label": "后市观点与策略",
         "text": _compose_ashare_outlook(market, bias)},
    ]
    return {
        "date": market.get("date") or "",
        "source": market.get("source") or "snapshot",
        "headline": _compose_ashare_headline(market, bias),
        "bias": bias,
        "indices": market.get("indices") or [],
        "leaders": market.get("leaders") or [],
        "laggards": market.get("laggards") or [],
        "turnover": market.get("turnover"),
        "breadth": market.get("breadth") or {},
        "points": points,
    }


# ---------------------------------------------------------------- 推送 HTML
def _esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def _trunc(s: str, n: int = 60) -> str:
    s = _esc(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def build_html(brief: dict, now: datetime | None = None, review: dict | None = None) -> str:
    """生成适合微信阅读的竖版长图文简报（内联样式，兼容 PushPlus HTML 模板）。

    视觉基调：电子杂志 × 电子墨水。页面以浅灰纸张为底，正文使用黑色，
    只用荧光绿和黑色做标题、标记与重点强调，避免邮件客户端中的复杂布局。
    ``now`` 保留在接口中以兼容现有调用，但报告标题不展示推送时间。
    ``review`` 为「前日 A 股复盘」结果；缺省时自动调用 analyze_ashare()（实时采集 → 快照兜底）。
    """
    # E-ink editorial palette: paper first, ink second, green only for emphasis.
    neon_green = "#b7ff00"
    ink = "#111311"
    black = "#0a0c0a"
    paper = "#ecefea"
    paper_lift = "#f7f8f5"
    muted = "#626a61"
    rule = "#c8cec5"
    danger = "#c2453b"       # 唯一新增辅助色：仅用于下跌/领跌数值与标记
    danger_hi = "#ff6b5c"    # 黑底上的下跌强调色
    font = "font-family:Arial,'PingFang SC','Microsoft YaHei','Noto Sans SC',sans-serif;"
    total = sum(len(items or []) for items in brief.values())

    source_cards = []
    for index, meta in enumerate(SOURCE_META, 1):
        items = brief.get(meta["name"], []) or []
        rows = []
        for item_index, item in enumerate(items, 1):
            title = _trunc(str(item.get("title", "")), 100)
            url = item.get("url") or ""
            title_html = (
                f'<a href="{_esc(url)}" style="color:{ink};text-decoration:underline;text-decoration-color:{neon_green};text-decoration-thickness:2px;">{title}</a>'
                if url else title
            )
            border = f'border-bottom:1px solid {rule};' if item_index < len(items) else ""
            rows.append(
                "<tr>"
                f'<td width="22" valign="top" style="width:22px;padding:8px 7px 8px 0;{border}color:{muted};font-size:11px;line-height:1.6;{font}">{item_index:02d}</td>'
                f'<td valign="top" style="padding:8px 0;{border}color:{ink};font-size:13px;line-height:1.65;word-break:break-all;{font}">{title_html}</td>'
                "</tr>"
            )
        if not rows:
            rows.append(
                f'<tr><td style="padding:8px 0;color:{muted};font-size:11px;{font}">暂未抓取到内容</td></tr>'
            )
        source_cards.append(
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'style="width:100%;margin:0 0 10px;background:{paper_lift};border:1px solid {black};border-top:4px solid {neon_green};">'
            f'<tr><td style="padding:10px 11px 3px;">'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
            f'<td style="color:{neon_green};background:{black};padding:3px 5px;font-size:12px;font-weight:700;line-height:1.4;word-break:break-all;{font}">{index:02d} · {_esc(meta["name"])}</td>'
            f'<td align="right" valign="top" style="padding-left:8px;white-space:nowrap;color:{ink};font-size:11px;line-height:1.8;{font}">{len(items)} 条</td>'
            f'</tr></table>'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;">{"".join(rows)}</table>'
            f'</td></tr></table>'
        )

    # 开篇 AI 总结：由 analyze_brief() 依据真实抓取结果动态生成，不再硬编码。
    analysis = analyze_brief(brief)
    # 需要荧光绿高亮的板块名：热度主线 + 利好/利差板块（去重保序）。
    hl_tags = list(dict.fromkeys(
        analysis["sectors"] + analysis["sectors_up"] + analysis["sectors_down"]
    ))

    def _hl(escaped_text: str) -> str:
        """在已转义文本中给板块名套上黑底荧光绿高亮。"""
        for tag in hl_tags:
            tag_esc = _esc(tag)
            escaped_text = escaped_text.replace(
                tag_esc,
                f'<span style="color:{neon_green};background:{black};padding:1px 3px;font-weight:700;">{tag_esc}</span>',
            )
        return escaped_text

    headline = _hl(_esc(analysis["headline"]))

    # 四个观点：市场情绪 / 多空博弈概率 / 利好·利差板块 / 资金流向分析。
    point_rows = []
    for point_index, point in enumerate(analysis["points"], 1):
        text = _esc(point["text"])
        if point["key"] in ("sectors", "flow"):
            text = _hl(text)
        point_rows.append(
            f'<tr><td width="24" valign="top" style="width:24px;padding:7px 6px 1px 0;color:{muted};font-size:11px;line-height:1.6;{font}">{point_index:02d}</td>'
            f'<td style="padding:7px 0 1px;color:{ink};font-size:12px;line-height:1.75;word-break:break-all;{font}">'
            f'<span style="color:{neon_green};background:{black};padding:1px 4px;font-size:10px;font-weight:700;line-height:1.5;">{_esc(point["label"])}</span>'
            f' {text}</td></tr>'
        )
    points_html = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="width:100%;margin:10px 0 0;border-top:1px dashed {rule};">'
        + "".join(point_rows)
        + "</table>"
    )

    # 最新 A 股复盘（六维度内容策略）：标题条 + AI 一句话 + 指数条 + 六个观点行 + 数据来源。
    if review is None:
        review = analyze_ashare()

    def _chip(text: str, color: str = neon_green) -> str:
        # 入参必须是已转义文本，这里不再重复转义。
        return (f'<span style="color:{color};background:{black};padding:1px 3px;'
                f'font-weight:700;">{text}</span>')

    def _hl_ashare(text: str) -> str:
        """复盘文本板块标记：领涨/流入 → 荧光绿，领跌/回避 → 砖红（先转义再替换）。"""
        escaped = _esc(text)
        for item in (review.get("leaders") or []):
            tag = _esc(item["name"])
            escaped = escaped.replace(tag, _chip(tag, neon_green))
        for item in (review.get("laggards") or []):
            tag = _esc(item["name"])
            escaped = escaped.replace(tag, _chip(tag, danger_hi))
        return escaped

    bias_color = neon_green if review["bias"] == "偏多" else (danger_hi if review["bias"] == "偏空" else "#ffffff")
    bias_pill = (
        f'<span style="color:{bias_color};background:{black};padding:2px 6px;'
        f'font-size:10px;font-weight:700;{font}">{_esc(review["bias"])}</span>'
    )

    index_cells = []
    for cell_index, index in enumerate(review.get("indices") or []):
        pct = index.get("pct") or 0
        color = neon_green if pct >= 0 else danger_hi
        arrow = "↑" if pct > 0 else ("↓" if pct < 0 else "·")
        border = "border-left:1px solid #3d463b;" if cell_index else ""
        index_cells.append(
            f'<td align="center" style="width:25%;padding:8px 2px;{border}">'
            f'<div style="color:#9aa396;font-size:10px;line-height:1.5;{font}">{_esc(index["name"])}</div>'
            f'<div style="color:{color};font-size:14px;font-weight:700;line-height:1.4;{font}">{arrow}{pct:+.2f}%</div>'
            f'<div style="color:#ffffff;font-size:10px;line-height:1.5;{font}">{index["close"]:.2f}</div>'
            f'</td>'
        )
    index_strip = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="width:100%;margin:9px 0 0;background:{black};"><tr>{"".join(index_cells)}</tr></table>'
    ) if index_cells else ""

    review_rows = []
    for point_index, point in enumerate(review.get("points") or [], 1):
        text = _esc(point["text"])
        if point["key"] in ("sectors", "funds", "outlook"):
            text = _hl_ashare(point["text"])
        review_rows.append(
            f'<tr><td width="24" valign="top" style="width:24px;padding:7px 6px 1px 0;color:{muted};font-size:11px;line-height:1.6;{font}">{point_index:02d}</td>'
            f'<td style="padding:7px 0 1px;color:{ink};font-size:12px;line-height:1.75;word-break:break-all;{font}">'
            f'<span style="color:{neon_green};background:{black};padding:1px 4px;font-size:10px;font-weight:700;line-height:1.5;">{_esc(point["label"])}</span>'
            f' {text}</td></tr>'
        )
    review_rows_html = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="width:100%;margin:10px 0 0;border-top:1px dashed {rule};">'
        + "".join(review_rows)
        + "</table>"
    )

    source_label = {
        "eastmoney": "东方财富行情接口",
        "tencent": "腾讯证券行情接口（备用）",
    }.get(review.get("source"), "内置真实快照")
    ashare_card = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="width:100%;margin:0 0 10px;background:{paper_lift};border:1px solid {black};border-top:4px solid {neon_green};">'
        f'<tr><td style="padding:11px 12px 12px;">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td style="color:{neon_green};background:{black};padding:2px 5px;font-size:10px;line-height:1.4;letter-spacing:1px;{font}">AI 复盘 · 最新 A 股</td>'
        f'<td align="right" valign="middle" style="white-space:nowrap;">{bias_pill} <span style="color:{muted};font-size:10px;{font}">{_esc(review.get("date") or "")}</span></td>'
        f'</tr></table>'
        f'<div style="margin:8px 0 0;color:{ink};font-size:14px;line-height:1.75;word-break:break-all;{font}">{_hl_ashare(review.get("headline") or "")}</div>'
        f'{index_strip}'
        f'{review_rows_html}'
        f'<div style="margin:8px 0 0;padding-top:6px;border-top:1px dashed {rule};color:{muted};font-size:10px;line-height:1.5;{font}">行情数据：{_esc(source_label)} · {_esc(review.get("date") or "")}</div>'
        f'</td></tr></table>'
    )

    intro = (
        "全网境内外为你寻找蛛丝马迹-提供全景视野分析。由多模型协同推理决策，"
        "底层所使用的大语言模型（LLM）多模式背后结合使用了多种不同的先进模型，"
        "包括但不限于 Claude、ChatGPT、Gemini、Grok、Qwen 以及 Kimi。"
        "根据不同的资产管理任务需求，更好地发挥各个模型的优势来提供数据支持！[加油]"
    )
    author = "作者：章鱼 ai　　仅供参考，分析研究"

    # 调研方法说明固定放在推送页最后：数据源流之后、页脚（免责声明/作者）之前。
    method_card = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;margin:0 0 10px;background:{paper_lift};border-left:4px solid {black};">'
        f'<tr><td style="padding:10px 12px;color:{ink};font-size:12px;line-height:1.7;{font}"><span style="color:{neon_green};background:{black};padding:2px 4px;font-size:10px;">调研方法</span><br>{_esc(intro)}</td></tr></table>'
    )

    return (
        f'<div style="width:100%;max-width:100%;margin:0;padding:12px 10px 20px;box-sizing:border-box;background:{paper};color:{ink};{font}word-break:break-word;">'
        # Editorial masthead: deliberately no PushPlus label and no timestamp.
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;margin:0 0 10px;background:{black};border-left:6px solid {neon_green};">'
        f'<tr><td style="padding:14px 13px 13px;">'
        f'<div style="margin:0 0 7px;color:{neon_green};font-size:10px;line-height:1.4;letter-spacing:1.5px;{font}">全网 AI 调研　/　境内 × 境外</div>'
        f'<div style="margin:0;color:{neon_green};font-size:23px;font-weight:800;line-height:1.25;letter-spacing:-.5px;{font}">章鱼 AI 全景分析</div>'
        f'<div style="margin:7px 0 0;color:#fff;font-size:12px;line-height:1.55;{font}">全网 AI 调研境内境外数据，由多个大模型混合部署。覆盖 {len(SOURCE_META)} 个数据源。</div>'
        f'</td></tr></table>'

        # One-line insight plus the four AI viewpoints, green-on-black highlights.
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;margin:0 0 10px;background:{paper_lift};border:1px solid {black};border-top:4px solid {neon_green};">'
        f'<tr><td style="padding:11px 12px 12px;">'
        f'<div style="margin:0 0 6px;color:{neon_green};background:{black};display:inline-block;padding:2px 5px;font-size:10px;line-height:1.4;letter-spacing:1px;{font}">AI 今天给你去噪音，留干货</div>'
        f'<div style="margin:0;color:{ink};font-size:14px;line-height:1.75;word-break:break-all;{font}">{headline}</div>'
        f'{points_html}'
        f'</td></tr></table>'

        # 最新 A 股六维度复盘：紧跟开篇 AI 总结，同属「开头 AI 部分」。
        + ashare_card

        # Compact report counters.
        + f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;margin:0 0 10px;background:{black};border:1px solid {black};">'
        f'<tr>'
        f'<td align="center" style="width:33.33%;padding:9px 4px;color:{neon_green};font-size:18px;font-weight:700;line-height:1.25;{font}">{len(SOURCE_META)}<br><span style="color:#fff;font-size:10px;font-weight:400;{font}">数据源</span></td>'
        f'<td align="center" style="width:33.33%;padding:9px 4px;color:{neon_green};font-size:18px;font-weight:700;line-height:1.25;border-left:1px solid #3d463b;border-right:1px solid #3d463b;{font}">{total}<br><span style="color:#fff;font-size:10px;font-weight:400;{font}">条快讯</span></td>'
        f'<td align="center" style="width:33.33%;padding:9px 4px;color:{neon_green};font-size:18px;font-weight:700;line-height:1.25;{font}">18<br><span style="color:#fff;font-size:10px;font-weight:400;{font}">境内外视野</span></td>'
        f'</tr></table>'

        + "".join(source_cards)

        # Method note sits at the very end of the push page (after the source
        # stream); only the disclaimer + author footer follow it.
        + method_card
        + f'<div style="margin:10px 0 0;color:{muted};font-size:10px;line-height:1.5;text-align:center;{font}">数据仅供参考，不构成投资建议</div>'
        + f'<div style="margin:8px 0 0;padding:10px 4px 0;border-top:1px solid {black};color:{black};font-size:11px;line-height:1.6;text-align:center;font-weight:700;{font}">{_esc(author)}</div>'
        + '</div>'
    )

if __name__ == "__main__":
    print(f"开始抓取 {len(SOURCES)} 个数据源…")
    data = collect_all()
    for name, items in data.items():
        print(f"  ✓ {name}: {len(items)} 条")
    print()
    print(build_html(data)[:600])
