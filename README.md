# 章鱼 AI·全景分析

移动端竖屏信息聚合面板原型，覆盖：

- 每日 12:30 / 19:30 双时段推送计划与开关
- 手动运行一次、倒计时反馈
- AI 一句话总结、股票主题高亮、AI 分析延展入口
- PushPlus 连接状态
- 12 个基础数据源与“增加内容与栏目”扩展入口
- 灰底深蓝字视觉规范

## 本地预览

```bash
# 必须通过此服务启动；python -m http.server 只是静态服务器，无法处理 POST /api/run。
PUSHPLUS_TOKEN=你的_PushPlus_token python3 server.py
```

## 后端接口对接

前端以相对路径调用服务端 API。此前项目只用静态服务器/静态托管部署，静态服务器不支持 `POST`，所以点击“立即运行一次”会收到 **405 Method Not Allowed**；这不是 PushPlus 的响应，推送请求还没有发出。

仓库现在提供了零依赖的 `server.py`：它同时提供页面和 API，避免浏览器跨域与静态服务器的 405。`PUSHPLUS_TOKEN` 只保留在服务端环境变量中，绝不能写进前端文件或提交到 Git。

- **`GET /api/sources`** — 返回来源名称数组。
- **`POST /api/run`** — 使用 `PUSHPLUS_TOKEN` 调用 PushPlus；未配置 token 时明确返回 503，不会伪造“已推送”。
- **`OPTIONS /api/*`** — 返回 CORS 预检响应。

页面资源带有版本查询参数，且服务端对 `index.html` 使用 `no-store`，以避免预览/CDN 继续展示旧 index。部署时请用 `python3 server.py` 作为启动命令、暴露 `PORT`，并在部署平台的机密环境变量中设置 `PUSHPLUS_TOKEN`。

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
