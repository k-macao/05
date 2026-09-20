# 正文最后的「全网快讯」列表口径

> 更新时间：**2026-09-20**（按五大板块分组；49 个数据源）
> 引擎入口：`sources.build_html()` → 内部 `_news_card()`；每源条数常量 `sources.NEWS_ITEMS_PER_SOURCE = 3`。

## 为什么这样排

四个分析栏目（AI 每日总结 / AI 板块机会 / AI 政策分析 / AI 看盘）负责给结论，
正文最后再用一个「全网快讯」卡片把当日抓到的**原始快讯**列出来，供读者自查证据。
列表放在免责声明与作者署名之前，是整份推送的最后一个内容板块。

## 三条硬规则

| 规则 | 说明 | 实现 |
| --- | --- | --- |
| **每源 3 条** | 49 个数据源（五大板块），每个源按抓取顺序取前 3 条，最多 147 行 | `NEWS_ITEMS_PER_SOURCE = 3`，`_news_card(per_source)` |
| **列在最后** | 位置固定：AI 看盘 → 全网快讯 → 免责声明 → 作者署名 | `build_html()._render_full()` 的拼接顺序 |
| **隐藏源头** | 只显示标题，不输出数据源名称，也不带跳转链接（避免域名反向暴露来源） | 行内只渲染 `_hl(_trunc(title, 60))`，无 `ev.source`、无 `<a>` |
| **按板块分组** | 按「板块 → 数据源」顺序列出，每个板块一行小标题（财经快讯 / 热搜热点 / 政策发布 · 官方信息源 / 全球政经媒体 / 公民科技 · 政治透明度）+ 该组条数；编号全表连续；没有内容的板块不出现 | `sources.SECTIONS` / `sources_in_section()`，小标题行复用 `td-hdr` 样式；板块名不是任何数据源名 |

来源被隐藏后，同一条新闻被多个源转载会重复出现，因此列表还会**跨源去重**：
按 `sources._news_key()`（忽略大小写、空白与标点的标题指纹）只保留首次出现的那一条，
卡片右上角的「共 N 条」是去重后的真实条数。

## 与推送容量口径的关系

- 默认（会员 10 万字 / 98,000 字符）：147 行全部列出，演示数据实测整份推送约 2.8 万字符，余量充足。
- `PUSHPLUS_MEMBER=0`（普通账号 2 万字 / 19,500 字符）：49 源 × 3 条放不下，自动收敛到每源 1 条
  （演示数据实测约 1.9 万字符），分析栏目不受影响。
- 字符上限不够时的收敛顺序（`build_html()` 末尾的循环）：
  **每源 3 条 → 2 条 → 1 条 → 整段省略**；四个分析栏目与作者署名始终保留。
- `PUSHPLUS_ITEMS_PER_SOURCE` 只能把条数往下压（如设 `1` 即每源 1 条）；
  设成大于 3 不会让快讯列表变长，多抓的条数用于分析栏目的信号统计。
- 标题按 60 字符截断（`_trunc`），并按分析栏目同一套板块词表做荧光绿高亮（`_hl`），
  HTML 全部经 `_esc()` 转义。

## 验收用例（`test_sources.py`）

- `test_build_html_default_quota_lists_three_per_source`：每源只保留前 3 条。
- `test_build_html_news_list_is_last_and_hides_sources`：位置在最后，且整段无来源名、无链接。
- `test_build_html_news_list_dedupes_across_sources`：跨源转载只列一次。
- `test_news_card_groups_by_section`（`SectionTest`）：按板块分组、编号连续、板块名不暴露来源。
- `test_build_html_news_list_omitted_when_brief_empty`：当日无快讯时整段省略。
- `test_build_html_news_list_titles_are_escaped`：标题转义，不把原始 HTML 带进推送。
- `test_raw_source_cards_replaced_by_anonymous_news_list`：旧的「监测平台列表 / 雷达矩阵」仍不渲染。
- `test_build_html_shrinks_news_list_before_dropping_it`：额度收紧时 3 → 2 → 1 → 省略。
