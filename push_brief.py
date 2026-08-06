#!/usr/bin/env python3
"""每日简报推送脚本：供 GitHub Actions 定时（12:30 / 19:30 北京时间）或手动触发。

用法：
    PUSHPLUS_TOKEN=xxx python3 push_brief.py
可选：
    PUSHPLUS_TOPIC=xxx       群组 topic
    PUSHPLUS_API_URL=...     覆盖推送地址（测试时指向本地假 PushPlus）

退出码：0 成功，1 未配置 token，2 推送失败。
"""
import json
import os
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import sources

API_URL = os.environ.get("PUSHPLUS_API_URL", "https://www.pushplus.plus/send")
SOURCES = sources.SOURCES

# PushPlus 官方返回码 → 排查建议（https://www.pushplus.plus/doc/guide/code.html）
PUSHPLUS_ERROR_HINTS = {
    302: "未登录",
    401: "请求未授权：请到 pushplus.plus 个人中心确认「开放接口」已启用",
    403: "请求 IP 未授权：若开启了 IP 白名单，请将 GitHub Actions 出口 IP 加入白名单（或直接关闭白名单）",
    500: "PushPlus 系统异常，请稍后重试",
    888: "积分不足：免费额度用尽，需等待额度恢复或充值",
    900: "请求次数过多、账号被限流：降低推送频率后再试",
    903: "无效的用户令牌：token 不正确或已失效，请重新登录 www.pushplus.plus 复制最新 token 并更新仓库 Secret PUSHPLUS_TOKEN",
    905: "账户未完成实名认证：到 pushplus.plus 完成实名认证后即可发送",
    999: (
        "服务端验证错误（具体原因在完整返回内容里，见上一行）。常见原因："
        "① 配置了 PUSHPLUS_TOPIC 但群组编码不存在/不属于该 token 的账号——可先删除仓库 Secret "
        "PUSHPLUS_TOPIC 改为一对一推送验证；② 账号实名认证过期，需重新认证；"
        "③ token 已失效，重新登录 www.pushplus.plus 复制最新 token"
    ),
}


def build_content(now):
    """真实抓取 18 个数据源并渲染 HTML 简报（网络不可用时自动回退内置演示数据）。"""
    try:
        brief = sources.collect_all()
    except Exception:
        brief = {}
    return sources.build_html(brief, now=now)


def main():
    token = os.environ.get("PUSHPLUS_TOKEN")
    if not token:
        print("错误：未配置 PUSHPLUS_TOKEN（请在仓库 Secrets 中设置）", flush=True)
        return 1

    # 诊断：打印 token 长度，帮助排查空白字符问题
    token = token.strip()
    print(f"诊断：PUSHPLUS_TOKEN 长度={len(token)}", flush=True)

    topic = os.environ.get("PUSHPLUS_TOPIC")
    if topic:
        topic = topic.strip() or None  # 与 token 一样去空白，防止 Secret 里混入换行/空格导致群组校验失败
    if topic:
        print(f"诊断：本次为一对多推送，携带群组 topic（长度={len(topic)}）", flush=True)
    else:
        print("诊断：本次为一对一推送（未配置 PUSHPLUS_TOPIC）", flush=True)

    payload = {
        "token": token,
        "title": "章鱼 AI·全景分析",
        "content": build_content(datetime.now()),
        "template": "html",
    }
    if topic:
        payload["topic"] = topic

    try:
        request = Request(
            API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=15) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        # HTTP 层失败时也尽量读出服务端返回体，避免丢失错误详情。
        detail = ""
        try:
            detail = error.read().decode("utf-8", "replace")
        except Exception:
            pass
        print(f"错误：PushPlus 请求失败：{error}；返回内容：{detail}", flush=True)
        return 2
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        print(f"错误：PushPlus 请求失败：{error}", flush=True)
        return 2

    if result.get("code") != 200:
        code = result.get("code")
        print(f"错误：PushPlus 拒绝：code={code}, msg={result.get('msg', '')}", flush=True)
        # 官方文档：code=999 等错误需「具体查看返回内容」，打印完整返回体定位根因。
        print(f"诊断：PushPlus 完整返回={json.dumps(result, ensure_ascii=False)}", flush=True)
        hint = PUSHPLUS_ERROR_HINTS.get(code)
        if hint:
            print(f"排查建议：{hint}", flush=True)
        return 2

    print(f"推送成功：{payload['title']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
