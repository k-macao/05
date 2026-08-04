# 章鱼 AI·全景分析

移动端竖屏信息聚合面板原型，覆盖：

- 每日 12:30 / 19:30 双时段推送计划与开关
- 手动运行一次、倒计时反馈
- AI 一句话总结、股票主题高亮、AI 分析延展入口
- PushPlus 连接状态
- 12 个基础数据源与“增加内容与栏目”扩展入口
- 灰底深蓝字视觉规范
- PushPlus / 微信 HTML 简报采用浅灰底、白色简洁卡片、克莱因蓝（#002FA7）字体与全内联移动端排版

## 本地预览

```bash
# 必须通过此服务启动；python -m http.server 只是静态服务器，无法处理 POST /api/run。
PUSHPLUS_TOKEN=你的_PushPlus_token python3 server.py
```

## 部署到 GitHub Pages（github.io）

本项目已启用 GitHub Pages：**https://k-macao.github.io/05/**（来源：`main` 分支根目录）。

GitHub Pages 是**纯静态托管**，无法运行 `server.py`，`POST /api/run` 必然返回 **405**——这是平台限制，不是代码问题。因此 github.io 上的推送改由 **GitHub Actions** 完成：

- **定时推送**：每天 04:30 / 11:30 UTC（即北京时间 **12:30 / 19:30**）执行 `push_brief.py` 调用 PushPlus。工作流文件内容在 **`docs/daily-push.workflow.yml`**——由于本仓库的自动化机器人没有 GitHub 的 `workflows` 权限，无法直接创建 `.github/workflows/` 文件，请合并 PR 后手动创建：把 `docs/daily-push.workflow.yml` 的内容粘贴到 `.github/workflows/daily-push.yml`（或用 GitHub 网页新建文件）。随后把 `PUSHPLUS_TOKEN`（可选 `PUSHPLUS_TOPIC`）加入仓库 **Settings → Secrets and variables → Actions**。
- **手动触发**：页面「立即运行一次」在 github.io 环境下会自动跳转到 Actions 工作流页面，点 **Run workflow** 即可手动推送一次（`workflow_dispatch`）。
- 定时任务只在**默认分支（main）**生效：合并 PR 到 main 后即开始按计划执行。

> 注意：前端请求一律使用**相对路径**（`api/sources`），因为 github.io 项目页挂在 `/05/` 子路径下。

## 本地预览（带后端，可选）

```bash
# server.py 同时提供页面与 API；仅本地/自有服务器开发时使用，github.io 用不到它。
PUSHPLUS_TOKEN=你的_PushPlus_token python3 server.py
```

`python -m http.server` 只是静态服务器，无法处理 `POST /api/run`（历史 405 的来源之一）。

## 12 个数据源真实抓取（sources.py）

`server.py` 与 `push_brief.py` 现在会**真实抓取 12 个数据源**，而非发送占位文案：

- `sources.py` 内置 12 个源的元信息（源头站 + 聚合通道）与抓取/解析逻辑，零第三方依赖（仅标准库）。
- 华尔街见闻 / 雪球 / 金十 / 法布等站点为 **JS 渲染/需登录**，直连只能拿到空壳，因此先走公开热榜聚合通道 rebang.vip（服务端渲染，标题与链接均回指源头原文）；聚合通道失败时回退源头站直连，再不行回退内置演示数据，保证任何环境都能出简报。
- 每个源默认取 **10 条**，多源会转发同一事件，接后端时可做去重。
- 完整抓取结果示例见 `docs/12数据源抓取结果.md`。

## 后端接口约定（server.py 本地开发用）

- **`GET /api/sources`** — 返回来源名称数组。
- **`GET /api/brief`** — 抓取并返回 12 个数据源的全量简报数据 `{name: [item,...]}`（带 5 分钟缓存）。
- **`POST /api/run`** — 真实抓取 12 个数据源、生成 HTML 简报后调用 PushPlus 推送；未配置 token 时明确返回 503，不会伪造“已推送”。
- **`OPTIONS /api/*`** — 返回 CORS 预检响应。

`PUSHPLUS_TOKEN` 只保留在服务端环境变量/仓库 Secrets 中，绝不能写进前端文件或提交到 Git。

## 手动推送联调测试（无需真实 token / 外网）

推送目标地址可用环境变量 `PUSHPLUS_API_URL` 覆盖（默认 `https://www.pushplus.plus/send`）。配合本仓库的本地假 PushPlus 服务 `mock_pushplus.py`，可以完整验证「手动推送 → 请求发出 → 载荷正确」这条链路：

```bash
# 1. 启动假 PushPlus：把收到的推送请求原样写入假文件 pushplus_record.json
PORT=4181 RECORD_FILE=pushplus_record.json python3 mock_pushplus.py

# 2. 启动 server.py，把推送目标指向假服务（token 随便填）
PORT=4182 PUSHPLUS_TOKEN=any PUSHPLUS_API_URL=http://127.0.0.1:4181/send python3 server.py

# 3. 执行手动推送（与页面「立即运行一次」相同）
curl -X POST -H "Content-Type: application/json" -d '{}' http://127.0.0.1:4182/api/run
# 期望：{"message": "简报已推送至 PushPlus"}（HTTP 200）

# 4. 检查假文件是否有内容：应包含 token / title / content / template 完整载荷
cat pushplus_record.json
```

自动化回归测试（覆盖 405 回归、503 无 token、推送成功写文件、推送被拒 502）：

```bash
python3 -m venv .venv
.venv/bin/python test_server.py
```

`MOCK_FAIL=1` 可让假服务模拟 PushPlus 拒绝（返回业务码 400），用于测试失败分支。
