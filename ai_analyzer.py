#!/usr/bin/env python3
"""章鱼 AI·全景分析 —— 逐条新闻 AI 分析引擎（零第三方依赖）。

对每条新闻标题进行关键词规则分析，输出：
  1. 利好 / 利空 / 中性 + 涉及板块
  2. 相关股票市场（A股 / 港股 / 美股 / 商品期货 / 外汇 / 多市场）
  3. 影响周期（短期 / 中期 / 长期）

设计说明
--------
- 本模块为**纯规则引擎**，不依赖外部 AI API，保证离线 / GitHub Actions 环境可用。
- 规则基于金融关键词词典 + 上下文语义加权，覆盖常见财经快讯场景。
- 后续可替换为 OpenAI / Claude 等 LLM 调用，接口保持不变。

对外接口
--------
    analyze_item(title: str) -> dict
        返回 {"sentiment": "利好"|"利空"|"中性",
               "sectors": ["板块1", ...],
               "market": "A股"|"港股"|"美股"|...,
               "timeframe": "短期"|"中期"|"长期",
               "summary": "一句话分析"}
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------- 板块关键词映射
# key = 板块名称, value = (关键词列表, 默认情绪权重 +1=利好 -1=利空 0=中性)
_SECTOR_KEYWORDS: dict[str, tuple[list[str], int]] = {
    "半导体": (["半导体", "芯片", "semiconductor", "费城半导体", "ARM", "台积电",
               "TSMC", "SOX", "晶圆", "光刻", "EUV", "HBM", "存储", "长鑫",
               "模拟芯片", "探针台", "矽电"], 0),
    "AI/算力": (["AI", "算力", "人工智能", "大模型", "GPT", "Claude", "Anthropic",
               "OpenAI", "数据中心", "NVL", "英伟达", "NVIDIA", "Palantir",
               "机器人", "自动驾驶", "AI应用", "AI泡沫", "AI基建", "云业务",
               "AWS", "算力硬件", "AI医疗", "AI职业培训"], 0),
    "光通信": (["光通信", "光纤", "Lumentum", "Coherent", "古河电工", "光互联",
               "光模块", "光缆", "光纤产能"], 0),
    "新能源/电力": (["新能源", "电力", "电网", "光伏", "风电", "储能", "充电桩",
                   "电气设备", "卡特彼勒", "电网投资"], 0),
    "医药/生物": (["医药", "生物", "CXO", "CRO", "GLP-1", "诺和诺德", "NVO",
                 "抗癌", "减肥药", "创新药", "Thorne", "医疗健康"], 0),
    "贵金属": (["黄金", "白银", "铂金", "钯金", "gold", "silver", "platinum",
              "palladium", "贵金属"], 0),
    "原油/能源": (["原油", "油价", "石油", "OPEC", "霍尔木兹", "能源", "天然气",
                 "柴油", "EIA", "API原油", "沙特阿美", "Aramco"], 0),
    "券商/金融": (["券商", "证券", "银行", "保险", "金融", "基金", "摩根",
                 "高盛", "小摩", "Blue Owl", "Citadel"], 0),
    "消费": (["消费", "零售", "餐饮", "麦当劳", "宝洁", "P&G", "PG.N",
             "白酒", "食品", "耐克", "Nike"], 0),
    "汽车": (["汽车", "自动驾驶", "L3", "L4", "新能源汽车", "EV", "特斯拉",
             "Tesla", "蔚来", "比亚迪"], 0),
    "房地产": (["房地产", "楼市", "地产", "豪宅", "土地", "房价", "开盘"], 0),
    "农业": (["农业", "玉米", "大豆", "小麦", "粮食", "猪肉", "养殖"], 0),
    "航空/航运": (["航空", "航运", "航线", "货船", "港口", "罢工", "空乘",
                 "EasyJet", "易捷航空", "红海"], 0),
    "矿业/有色": (["矿业", "有色", "稀土", "钪", "锗", "铜", "铅", "锌",
                 "银矿", "矿产", "NioCorp", "Rare Earth", "盛达资源",
                 "磷矿", "川发龙蟒", "中金岭南"], 0),
    "化工": (["化工", "鲁西化工", "磷化工", "龙蟒"], 0),
    "TMT": (["TMT", "科创", "创业板", "互联网", "亚马逊", "Amazon", "阿里",
            "传智教育"], 0),
    "外汇": (["外汇", "日元", "欧元", "英镑", "汇市", "干预汇",
             "套利交易", "carry trade",
             "美联储", "Fed", "BOJ", "英国央行", "贝森特", "Bessent",
             "鸽派", "鹰派", "美元指数"], 0),
    "债券": (["债券", "国债", "收益率", "逆回购", "流动性", "利率",
             "央行"], 0),
    "地缘政治": (["地缘", "伊朗", "美伊", "战争", "冲突", "制裁", "谈判",
                "外交", "阿曼", "特朗普", "关税", "禁令"], 0),
}

# ---------------------------------------------------------------- 情绪关键词
_BULLISH_WORDS = [
    "涨", "大涨", "暴涨", "上涨", "拉升", "走高", "高开", "反攻", "反弹",
    "新高", "突破", "扩大", "强势", "爆发", "修复", "回升", "增长", "增持",
    "利好", "超预期", "上调", "提升", "翻倍", "扩产", "募集", "收购",
    "开门红", "日光", "hot", "surge", "rally", "soar", "jump", "gain",
    "改善", "回暖", "提振", "业绩炸场", "盈利王", "蓝海", "缓和",
]

_BEARISH_WORDS = [
    "跌", "大跌", "暴跌", "下跌", "重挫", "走低", "低开", "承压", "回落",
    "新低", "萎缩", "风险", "危机", "逾期", "诉讼", "立案", "退市",
    "罢工", "制裁", "禁止", "禁令", "冲击", "冲突", "战争", "封锁",
    "担忧", "鹰派", "减持", "下调", "降至", "降级", "泡沫", "停产",
    "drop", "fall", "plunge", "decline", "slump", "crash", "cut",
    "违规", "抹黑", "放缓", "警告", "扰动", "负面",
]

# ---------------------------------------------------------------- 市场关键词
_MARKET_KEYWORDS: dict[str, list[str]] = {
    "A股": ["A股", "沪深", "创业板", "科创板", "科创50", "上证", "深证",
           "A 股", ".SZ", ".SH", "000", "001", "002", "003", "300", "301",
           "600", "603", "688", "北交所",
           # A股常见源
           "财联社", "联创光电", "矽电股份", "盛达资源", "鲁西化工",
           "胜通能源", "川发龙蟒", "传智教育", "英特集团", "中金岭南",
           "萃华", "长鑫科技"],
    "港股": ["港股", "恒生", "港交所", "HK", ".HK", "香港上市",
           "格隆汇", "阿里", "腾讯", "美团", "小米"],
    "美股": ["美股", "标普", "纳指", "道指", "S&P", "Nasdaq", "Dow",
           "NYSE", ".N", "PG.N", "NVO.N", "费城半导体",
           "亚马逊", "Amazon", "Palantir", "ARM", "Lumentum", "Coherent",
           "OpenAI", "Anthropic", "Tesla", "特斯拉", "麦当劳",
           "洛克希德", "Lockheed", "卡特彼勒", "Caterpillar",
           "宝洁", "耐克", "Nike"],
    "商品期货": ["原油", "油价", "黄金", "白银", "铂金", "钯金",
               "铜价", "铁矿", "螺纹", "大宗商品", "期货",
               "WTI", "Brent", "COMEX"],
    "外汇": ["日元", "欧元", "美元指数", "英镑", "汇市", "外汇",
            "DXY", "JPY", "EUR", "GBP", "干预汇", "鸽派", "鹰派"],
    "债券": ["国债", "收益率", "债券", "逆回购"],
}

# ---------------------------------------------------------------- 时间周期关键词
_SHORT_TERM = [
    "今日", "盘中", "日内", "异动", "快讯", "电报", "实时", "即时",
    "拉升", "高开", "低开", "尾盘", "收盘", "开盘", "盘前",
    "涨停", "跌停", "分钟", "小时", "today", "intraday",
    "扩大", "缩窄",
]

_MEDIUM_TERM = [
    "季度", "Q1", "Q2", "Q3", "Q4", "月度", "月报", "财报",
    "业绩", "财年", "半年", "季报", "上调", "下调", "预期",
    "募集", "收购", "并购", "谈判", "增持", "减持", "罢工",
    "投资", "产能", "扩产", "订单",
]

_LONG_TERM = [
    "长期", "战略", "政策", "强标", "实施", "规划", "制度",
    "立法", "改革", "转型", "格局", "趋势", "时代", "十年",
    "指南", "条件", "流程", "基地", "建设",
]


def _match_count(text: str, keywords: list[str]) -> int:
    """统计 text 中匹配的关键词数量（不区分大小写）。"""
    lower = text.lower()
    return sum(1 for kw in keywords if kw.lower() in lower)


def _match_any(text: str, keywords: list[str]) -> bool:
    lower = text.lower()
    return any(kw.lower() in lower for kw in keywords)


def analyze_item(title: str) -> dict:
    """分析单条新闻标题，返回结构化分析结果。

    Returns:
        {"sentiment": "利好"|"利空"|"中性",
         "sectors": ["板块1", ...],
         "market": "A股"|"港股"|"美股"|...,
         "timeframe": "短期"|"中期"|"长期",
         "summary": "一句话分析"}
    """
    if not title or not title.strip():
        return {
            "sentiment": "中性",
            "sectors": [],
            "market": "—",
            "timeframe": "短期",
            "summary": "",
        }

    text = title.strip()

    # 1) 识别涉及的板块
    matched_sectors = []
    for sector, (keywords, _) in _SECTOR_KEYWORDS.items():
        if _match_any(text, keywords):
            matched_sectors.append(sector)

    # 2) 判断利好/利空
    bull_score = _match_count(text, _BULLISH_WORDS)
    bear_score = _match_count(text, _BEARISH_WORDS)

    if bull_score > bear_score:
        sentiment = "利好"
    elif bear_score > bull_score:
        sentiment = "利空"
    else:
        sentiment = "中性"

    # 3) 判断涉及的市场
    market_scores: dict[str, int] = {}
    for market, keywords in _MARKET_KEYWORDS.items():
        score = _match_count(text, keywords)
        if score > 0:
            market_scores[market] = score

    if not market_scores:
        # 根据板块推断
        if any(s in matched_sectors for s in ["贵金属", "原油/能源"]):
            market = "商品期货"
        elif "外汇" in matched_sectors:
            market = "外汇"
        elif "债券" in matched_sectors:
            market = "债券"
        elif any(s in matched_sectors for s in ["地缘政治"]):
            market = "多市场"
        else:
            market = "多市场"
    elif len(market_scores) == 1:
        market = list(market_scores.keys())[0]
    else:
        # 取得分最高的市场
        market = max(market_scores, key=market_scores.get)

    # 4) 判断影响周期
    short_score = _match_count(text, _SHORT_TERM)
    medium_score = _match_count(text, _MEDIUM_TERM)
    long_score = _match_count(text, _LONG_TERM)

    if long_score > medium_score and long_score > short_score:
        timeframe = "长期"
    elif medium_score > short_score:
        timeframe = "中期"
    else:
        timeframe = "短期"

    # 5) 生成一句话分析
    if not matched_sectors:
        sector_text = "综合市场"
    else:
        sector_text = "、".join(matched_sectors[:3])

    summary = f"{sentiment}{sector_text}｜{market}｜{timeframe}影响"

    return {
        "sentiment": sentiment,
        "sectors": matched_sectors[:3],
        "market": market,
        "timeframe": timeframe,
        "summary": summary,
    }


def analyze_items(items: list[dict]) -> list[dict]:
    """批量分析一组新闻条目，为每条附加 'analysis' 字段。

    Args:
        items: [{"title": "...", "url": "..."}, ...]

    Returns:
        同样的列表，每个 item 增加 "analysis" 键。
    """
    for item in items:
        item["analysis"] = analyze_item(item.get("title", ""))
    return items


# ---------------------------------------------------------------- 颜色/样式常量（供 build_html 使用）
SENTIMENT_STYLES = {
    "利好": {"color": "#16a34a", "bg": "#f0fdf4", "icon": "▲"},
    "利空": {"color": "#dc2626", "bg": "#fef2f2", "icon": "▼"},
    "中性": {"color": "#9333ea", "bg": "#faf5ff", "icon": "●"},
}


if __name__ == "__main__":
    # 简单测试
    test_titles = [
        "标普500涨幅扩大至1.5%，道指涨925点，半导体指数涨超6%",
        "债务逾期、25起诉讼待解、公司及实控人被立案 联创光电面临多重危机",
        "L3、L4级自动驾驶强标明年7月实施 明确安全主体责任、接管机制",
        "现货铂金上涨超过7%，报1,745.93美元/盎司",
        "日元又成了全世界的问题？全球最关键套利交易遭降维打击",
        "美国拟禁止进口中国新型数据中心设备，我使馆敦促美停止抹黑中企并威胁制裁",
        "矽电股份(301629)：将继续聚焦探针台领域",
        "诺和诺德2026年业绩前景改善，谈及GLP-1销售",
    ]
    for t in test_titles:
        result = analyze_item(t)
        print(f"  [{result['sentiment']}] {result['summary']}")
        print(f"    板块: {result['sectors']}  市场: {result['market']}  周期: {result['timeframe']}")
        print(f"    标题: {t[:60]}")
        print()
