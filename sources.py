#!/usr/bin/env python3
"""章鱼 AI·全景分析 —— 18 个数据源抓取采集器（零第三方依赖，仅标准库）。

为什么这么设计
------------
- 华尔街见闻 / 雪球 / 金十 / 法布等站点页面为 **前端 JS 渲染**，部分还需登录，
  直接 GET 只能拿到空壳，无法解析出条目。
- 因此每个源同时记录“源头站”(origin) 与一个公开的**热榜聚合通道** rebang.vip
  （该聚合页为服务端渲染，标题与链接均回指源头站原文，是稳定的抓取通道）。
- 新增 6 个热搜/热点源（知乎、抖音、微博、虎扑、AI Hot、联合早报）来自
  ourongxing/newsnow 项目，使用直接 API / HTML 抓取。
- 抓取顺序：自定义收集器 / 聚合通道 → 内置演示数据兜底，
  保证任何环境（本地 / GitHub Pages / GitHub Actions）都能稳定出结果。

对外接口
--------
    SOURCES            : 18 个源的名称列表（与前端 /api/sources、推送保持一致）
    SOURCE_META        : 每个源的元信息（name / origin / channel / collector）
    collect_all()      : 依次抓取全部 18 个源，返回 {name: [item, ...]}
    collect_one(name)  : 抓取单个源，返回 [item, ...]
    build_html(brief)  : 由采集结果生成可推送给 PushPlus 的 HTML 简报
"""
from __future__ import annotations

import html
import json
import re
import time
from datetime import datetime
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
    {"name": "联合早报",        "collector": "zaobao"},
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
    ],
    "微博实时热搜": [
        "高考成绩陆续公布",
        "某明星官宣结婚",
        "暑期档电影推荐",
        "高温预警 注意防暑",
        "国足世预赛最新战报",
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
    "联合早报": [
        "中美经贸高层会谈在日内瓦举行",
        "东南亚国家联盟峰会聚焦区域经济",
        "新加坡推出新一轮经济刺激计划",
        "全球气候变化会议最新进展",
        "亚太地区科技投资趋势分析",
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


def _collect_zaobao(limit: int) -> list:
    """联合早报 - 通过早晨报聚合，需要 gb2312 解码。"""
    url = "https://www.zaochenbao.com/realtime/"
    req = Request(url, headers={"User-Agent": UA}, method="GET")
    with urlopen(req, timeout=TIMEOUT) as resp:
        raw_bytes = resp.read()
    # gb2312 解码
    raw = raw_bytes.decode("gb2312", "replace")
    # 解析 <div class="list-block"><a class="item" href="...">...</a></div>
    parser = LinkCollector()
    parser.feed(raw)
    items = []
    base = "https://www.zaochenbao.com"
    seen = set()
    for href, text in parser.links:
        if "list-block" not in str(href) and href.startswith("/"):
            # 这是联合早报的文章链接
            if href in seen:
                continue
            seen.add(href)
            title = _collapse(text)
            if title:
                items.append({"title": title, "url": base + href})
                if len(items) >= limit:
                    break
    return items


# 收集器函数映射表
_COLLECTORS = {
    "zhihu": _collect_zhihu,
    "douyin": _collect_douyin,
    "weibo": _collect_weibo,
    "hupu": _collect_hupu,
    "aihot": _collect_aihot,
    "zaobao": _collect_zaobao,
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
        result[meta["name"]] = collect_one(meta["name"], limit)
    return result


# ---------------------------------------------------------------- 推送 HTML
def _esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def _trunc(s: str, n: int = 60) -> str:
    s = _esc(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def build_html(brief: dict, now: datetime | None = None) -> str:
    """把简报渲染成适合 PushPlus / 微信阅读的卡片式 HTML。

    PushPlus 的 HTML 会直接进入微信内置浏览器，不能依赖本站 CSS 或脚本。
    因此这里坚持：所有样式内联、宽度始终 100%、内容可断行、使用 table
    作为条目布局，并避免微信容易吞掉的外部字体、定位和复杂动画。
    """
    now = now or datetime.now()
    # 克莱因蓝作为主色，灰色只用于层级较低的辅助文字；样式全部内联，
    # 确保 PushPlus 转发到微信后仍保持同一套排版。
    blue = "#002FA7"
    ink = "#173A83"
    secondary = "#5D76A9"
    light_blue = "#EDF2FF"
    page = "#F2F3F5"
    line = "#E3E8F1"
    total = sum(len(items or []) for items in brief.values())

    source_cards = []
    for index, meta in enumerate(SOURCE_META, 1):
        items = brief.get(meta["name"], []) or []
        rows = []
        for item_index, item in enumerate(items, 1):
            title = _trunc(str(item.get("title", "")), 100)
            url = item.get("url") or ""
            title_html = (
                f"<a href=\"{_esc(url)}\" style=\"color:{blue};text-decoration:none;\">"
                f"{title}</a>"
                if url else title
            )
            border = f"border-bottom:1px solid {line};" if item_index < len(items) else ""
            rows.append(
                "<tr>"
                f"<td width=\"24\" valign=\"top\" style=\"width:24px;padding:10px 8px 10px 0;{border}"
                f"color:{blue};font-size:12px;line-height:1.6;\">{item_index:02d}</td>"
                f"<td valign=\"top\" style=\"padding:10px 0;{border}color:{ink};font-size:14px;"
                f"line-height:1.7;word-break:break-all;overflow-wrap:anywhere;\">{title_html}</td>"
                "</tr>"
            )
        if not rows:
            rows.append(
                f"<tr><td style=\"padding:10px 0;color:{secondary};font-size:13px;\">"
                "暂未抓取到内容</td></tr>"
            )
        source_cards.append(
            f"<table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" "
            f"border=\"0\" style=\"width:100%;margin:0 0 12px;background:#FFFFFF;border:1px solid {line};"
            f"border-radius:12px;\"><tr><td style=\"padding:14px 14px 4px;\">"
            f"<table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" "
            f"border=\"0\"><tr><td style=\"color:{blue};font-size:16px;font-weight:700;line-height:1.45;"
            f"word-break:break-all;\">{index:02d} · {_esc(meta['name'])}</td>"
            f"<td align=\"right\" valign=\"top\" style=\"padding-left:8px;white-space:nowrap;"
            f"color:{blue};font-size:11px;line-height:1.8;\">{len(items)} 条</td></tr></table>"
            f"<table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" "
            f"border=\"0\" style=\"width:100%;\">{''.join(rows)}</table>"
            "</td></tr></table>"
        )

    return (
        f"<div style=\"width:100%;max-width:100%;margin:0;padding:16px 12px 24px;box-sizing:border-box;"
        f"background:{page};color:{ink};font-family:-apple-system,BlinkMacSystemFont,'PingFang SC',"
        f"'Microsoft YaHei',Arial,sans-serif;word-break:break-word;overflow-wrap:anywhere;\">"
        f"<table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" border=\"0\" "
        f"style=\"width:100%;margin:0 0 12px;background:#FFFFFF;border:1px solid {line};border-radius:12px;\">"
        f"<tr><td style=\"padding:20px 16px 16px;\">"
        f"<div style=\"margin:0 0 9px;color:{blue};font-size:11px;line-height:1.4;letter-spacing:1px;\">"
        "AI INFORMATION BRIEF</div>"
        f"<div style=\"margin:0;color:{blue};font-size:25px;font-weight:700;line-height:1.35;"
        f"letter-spacing:-.5px;\">章鱼 AI·全景分析</div>"
        f"<div style=\"margin:8px 0 0;color:{secondary};font-size:12px;line-height:1.5;\">"
        f"{now:%Y年%m月%d日 %H:%M} 更新 · 覆盖 {len(SOURCE_META)} 个数据源 · 每日两次推送</div>"
        "</td></tr></table>"
        f"<table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" border=\"0\" "
        f"style=\"width:100%;margin:0 0 12px;background:#FFFFFF;border:1px solid {line};border-left:3px solid {blue};"
        f"border-radius:12px;\"><tr><td style=\"padding:16px;\">"
        f"<div style=\"margin:0 0 7px;color:{secondary};font-size:12px;line-height:1.4;\">今日一句话</div>"
        f"<div style=\"margin:0;color:{ink};font-size:16px;line-height:1.8;word-break:break-all;\">"
        f"市场风险偏好回升，<span style=\"color:{blue};font-weight:700;background:{light_blue};\">"
        "AI 算力与电网投资</span>仍是资金聚焦主线，但短期需警惕高位分化。</div>"
        f"<div style=\"margin:12px 0 0;color:{blue};font-size:11px;line-height:1.4;\">"
        "偏多　·　科技 / 能源</div>"
        "</td></tr></table>"
        f"<table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" border=\"0\" "
        f"style=\"width:100%;margin:0 0 12px;background:{light_blue};border:1px solid #DCE6FF;border-radius:12px;\">"
        f"<tr><td align=\"center\" style=\"width:33.33%;padding:12px 4px;color:{blue};font-size:20px;"
        f"font-weight:700;line-height:1.3;\">{len(SOURCE_META)}<br><span style=\"color:{secondary};font-size:11px;"
        f"font-weight:400;\">数据源</span></td>"
        f"<td align=\"center\" style=\"width:33.33%;padding:12px 4px;color:{blue};font-size:20px;"
        f"font-weight:700;line-height:1.3;border-left:1px solid #DCE6FF;border-right:1px solid #DCE6FF;\">"
        f"{total}<br><span style=\"color:{secondary};font-size:11px;font-weight:400;\">条快讯</span></td>"
        f"<td align=\"center\" style=\"width:33.33%;padding:12px 4px;color:{blue};font-size:20px;"
        f"font-weight:700;line-height:1.3;\">2<br><span style=\"color:{secondary};font-size:11px;"
        f"font-weight:400;\">今日推送</span></td></tr></table>"
        + "".join(source_cards)
        + f"<div style=\"padding:4px 4px 0;color:{secondary};font-size:11px;line-height:1.7;text-align:center;\">"
        "数据仅供参考，不构成投资建议</div></div>"
    )


if __name__ == "__main__":
    print(f"开始抓取 {len(SOURCES)} 个数据源…")
    data = collect_all()
    for name, items in data.items():
        print(f"  ✓ {name}: {len(items)} 条")
    print()
    print(build_html(data)[:600])
