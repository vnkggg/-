#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==================================================
东风日产任务监控脚本（青龙面板适配版）
==================================================
一、环境变量配置（必填）
1. 变量名：DFRC
2. 变量值格式：uuid#token#noncestr#sign（4个参数用#分隔，顺序不可乱）
3. 参数来源：从东风日产App任务列表接口抓包获取（请求头中对应字段）
4. 青龙面板设置路径：环境变量 → 添加变量 → 输入名称和值 → 保存

二、通知功能说明（青龙面板内置）
1. 通知渠道：自动复用青龙面板已配置的渠道（微信、Telegram、钉钉、企业微信等）
2. 触发场景：
   - 脚本启动通知：告知脚本已正常运行
   - 新增任务通知：推送新增任务的名称、平台、奖励、名额、有效期
   - 任务更新通知：推送任务剩余名额/天数的变化
   - 参数过期通知：提醒及时更新DFRC环境变量中的鉴权参数
3. 配置要求：青龙面板「系统设置」→「通知设置」中启用对应渠道，无需额外修改脚本
4. 关闭通知：若需关闭，可注释掉脚本中所有send_notify()调用

三、脚本功能
- 实时监控taskType=2/3类型任务（已知有任务的类型）
- 自动对比任务变化，识别新增/状态更新
- 鉴权参数过期时支持一键更新（无需重启脚本）
- 本地保存任务历史，重启后不丢失监控状态
- 可配置定时检测规则（高峰时段短间隔，其他时段长间隔）
==================================================
"""

import requests
import time
import json
import os
from datetime import datetime

# -------------------------- 基础配置（可按需修改）--------------------------
BASE_URL = "https://ariya-api.dongfeng-nissan.com.cn/nissan-partner-audit-service/api/task/v2/list"
DFRC_ENV = os.getenv("DFRC")
if not DFRC_ENV or len(DFRC_ENV.split("#")) != 4:
    raise ValueError(
        "❌ 环境变量DFRC配置错误！\n"
        "请按格式设置：uuid#token#noncestr#sign\n"
        "青龙面板路径：环境变量 → 添加变量"
    )
UUID, TOKEN, NONCESTR, SIGN = DFRC_ENV.split("#")

# 检测时间配置（可更改）
START_HOUR = 9    # 高峰检测开始时间（24小时制）
END_HOUR = 12     # 高峰检测结束时间（24小时制）
INTERVAL_PEAK = 30 * 60  # 高峰时段检测间隔（秒），默认30分钟
INTERVAL_OFF_PEAK = 3 * 60 * 60  # 非高峰时段检测间隔（秒），默认3小时

MONITOR_TASK_TYPES = [2, 3]
SAVE_HISTORY_PATH = "/ql/scripts/task_history_auth.json"  # 青龙面板脚本目录
AUTH_REMIND_INTERVAL = 30
# 通知配置（青龙面板自动识别）
NOTIFY_URL = os.getenv("QlNotifyUrl")  # 青龙通知接口

HEADERS = {
    "uuid": UUID,
    "appCode": "nissan",
    "clientid": "nissanapp",
    "token": TOKEN,
    "noncestr": NONCESTR,
    "sign": SIGN,
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148/NissanOneApp",
    "Origin": "https://www.dongfeng-nissan.com.cn",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh-Hans;q=0.9",
    "Connection": "keep-alive"
}

# -------------------------- 核心功能 --------------------------
def send_notify(title, content):
    """调用青龙面板通知接口，支持微信/Telegram/钉钉等"""
    if not NOTIFY_URL:
        print("ℹ️  未检测到青龙通知接口，跳过通知")
        return
    try:
        # 适配青龙通知格式
        data = {
            "title": title,
            "content": content,
            "to": "",  # 留空则使用面板默认接收人
            "token": os.getenv("QlToken", ""),
            "priority": "high"
        }
        response = requests.post(
            NOTIFY_URL,
            headers={"Content-Type": "application/json"},
            data=json.dumps(data),
            timeout=10
        )
        response.raise_for_status()
        print(f"✅ 通知发送成功：{title}")
    except Exception as e:
        print(f"❌ 通知发送失败：{str(e)}")

def reload_env_params():
    global UUID, TOKEN, NONCESTR, SIGN, HEADERS
    DFRC_ENV = os.getenv("DFRC")
    if not DFRC_ENV or len(DFRC_ENV.split("#")) != 4:
        print("❌ 环境变量DFRC格式错误！")
        return False
    UUID, TOKEN, NONCESTR, SIGN = DFRC_ENV.split("#")
    HEADERS.update({
        "uuid": UUID,
        "token": TOKEN,
        "noncestr": NONCESTR,
        "sign": SIGN
    })
    print("✅ 环境变量参数重新加载完成！")
    return True

def load_history_tasks():
    try:
        with open(SAVE_HISTORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_history_tasks(history):
    with open(SAVE_HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def fetch_tasks(task_type):
    params = {
        "pageIndex": 1,
        "pageSize": 20,
        "findMyTask": 0,
        "channelType": 1,
        "isPrecisePush": 1,
        "taskType": task_type
    }
    try:
        response = requests.get(
            BASE_URL, 
            headers=HEADERS, 
            params=params, 
            timeout=15,
            allow_redirects=False
        )
        
        if response.status_code in [401, 302]:
            msg = "鉴权参数过期/无效！请更新环境变量DFRC"
            print(f"\n❌ {msg}")
            send_notify("【东风日产任务监控】参数过期提醒", msg)  # 参数过期通知
            print("设置完成后按回车继续...")
            input()
            if not reload_env_params():
                time.sleep(AUTH_REMIND_INTERVAL)
                return fetch_tasks(task_type)
            return fetch_tasks(task_type)
        
        response.raise_for_status()
        data = response.json()
        return (data.get("rows", []), data.get("records", 0)) if data.get("result") == "1" else ([], 0)
    except Exception as e:
        print(f"❌ taskType={task_type}：请求失败：{str(e)}")
        return [], 0

def compare_tasks(old_tasks, new_tasks):
    old_ids = set(old_tasks.keys())
    new_ids = set(t["taskId"] for t in new_tasks)
    新增 = [t for t in new_tasks if t["taskId"] not in old_ids]
    变化 = []
    for task_id in old_ids & new_ids:
        old = old_tasks[task_id]
        new = next(t for t in new_tasks if t["taskId"] == task_id)
        if old["taskSurplusNum"] != new["taskSurplusNum"] or old["taskSurplusDay"] != new["taskSurplusDay"]:
            变化.append({
                "name": new["taskName"],
                "change": f"名额：{old['taskSurplusNum']}→{new['taskSurplusNum']} | 天数：{old['taskSurplusDay']}→{new['taskSurplusDay']}"
            })
    return 新增, 变化

def get_current_interval():
    """根据当前时间返回对应检测间隔"""
    current_hour = datetime.now().hour
    if START_HOUR <= current_hour < END_HOUR:
        interval = INTERVAL_PEAK
        print(f"⏰ 当前为高峰时段（{START_HOUR}-{END_HOUR}点），检测间隔：{interval//60}分钟")
    else:
        interval = INTERVAL_OFF_PEAK
        print(f"⏰ 当前为非高峰时段，检测间隔：{interval//60}分钟")
    return interval

# -------------------------- 主逻辑 --------------------------
def main():
    start_title = "东风日产任务监控脚本启动"
    start_content = (
        f"监控类型：{MONITOR_TASK_TYPES}\n"
        f"高峰时段：{START_HOUR}-{END_HOUR}点（间隔{INTERVAL_PEAK//60}分钟）\n"
        f"非高峰时段：间隔{INTERVAL_OFF_PEAK//60}分钟\n"
        "已加载鉴权参数"
    )
    print(f"🚀 {start_title}（{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}）")
    send_notify(start_title, start_content)  # 启动通知
    
    history = load_history_tasks()

    while True:
        print(f"\n{'='*50}")
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"⌛ 检测时间：{current_time}")

        for task_type in MONITOR_TASK_TYPES:
            new_tasks, total = fetch_tasks(task_type)
            old_tasks = history.get(str(task_type), {})
            print(f"\n📊 taskType={task_type}：共{total}条任务")

            if not new_tasks and total == 0:
                continue

            new_dict = {t["taskId"]: t for t in new_tasks}
            新增任务, 变化任务 = compare_tasks(old_tasks, new_tasks)

            # 新增任务通知
            if 新增任务:
                title = f"【新增任务】taskType={task_type}"
                content = "\n\n".join([
                    f"任务名称：{t['taskName']}\n"
                    f"发布平台：{t['platForm']}\n"
                    f"奖励积分：{t['rewardScoreString']}\n"
                    f"剩余名额：{t['taskSurplusNum']}\n"
                    f"剩余天数：{t['taskSurplusDay']}\n"
                    f"有效期：{t['taskBeginTime']} 至 {t['taskEndTime']}"
                    for t in 新增任务
                ])
                print(f"🎉 {title}")
                print(content)
                send_notify(title, content)  # 发送新增通知

            # 任务变化通知
            if 变化任务:
                title = f"【任务更新】taskType={task_type}"
                content = "\n\n".join([
                    f"任务名称：{t['name']}\n"
                    f"变化内容：{t['change']}"
                    for t in 变化任务
                ])
                print(f"🔄 {title}")
                print(content)
                send_notify(title, content)  # 发送变化通知

            history[str(task_type)] = new_dict

        save_history_tasks(history)
        # 获取当前应使用的间隔
        current_interval = get_current_interval()
        print(f"\n✅ 本次检测完成，等待{current_interval//60}分钟...")
        time.sleep(current_interval)

if __name__ == "__main__":
    main()
