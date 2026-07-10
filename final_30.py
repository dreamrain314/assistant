# -*- coding: utf-8 -*-
"""30 例全链路实测：route_intent → classify_and_extract → 完整提取结果"""
import sys, io, json, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from dotenv import load_dotenv; load_dotenv()
import app

USER = '管理员'  # 当前登录用户

cases = [
    # ====== 帮别人完成任务（核心测试） ======
    ("01", "张三的工作报告我已经帮他交了"),
    ("02", "李四的代码审查我帮他做完了"),
    ("03", "王五的安全巡检记录我已经替他完成了"),
    ("04", "小龙的试卷我帮忙改好了"),
    ("05", "小红那份隐患排查台账我替她搞定了"),

    # ====== 自己完成任务（各种说法） ======
    ("06", "我完成了'年度安全工作总结'"),
    ("07", "那个工作票我已经处理掉了"),
    ("08", "'继保测试数据'提交了"),
    ("09", "两份操作票都办完了"),
    ("10", "昨天搞定了安全培训记录"),

    # ====== 布置任务（给他人） ======
    ("11", "张工明天要完成'变电站接地测试报告'"),
    ("12", "安排李工下周五前写完安全评估方案"),
    ("13", "王主任需要提交一季度事故统计分析"),
    ("14", "帮我在'有限空间作业审批'上加个截止时间这周五"),
    ("15", "赵工有一个'配电线路检修台账'要更新，后天截止"),

    # ====== 布置任务（给自己） ======
    ("16", "我明天要交'安全巡检月报'"),
    ("17", "我自己要完成年度供电可靠性统计"),
    ("18", "帮我自己安排一个'反事故演练方案'的修改任务"),

    # ====== 修改/更新 ======
    ("19", "把张工的接地测试报告改到下周交"),
    ("20", "变电站巡检报告标记为已完成"),
    ("21", "隐患整改台账的截止时间提前到明天"),

    # ====== 查询 ======
    ("22", "今天有哪些任务"),
    ("23", "张工还有几个没完成的"),
    ("24", "这周安全检测相关的任务有哪些"),

    # ====== 易混淆边界 ======
    ("25", "那个写代码的任务我搞定了"),        # 我搞定别人的任务
    ("26", "我做完了张工安排的安全培训"),       # 谁的任务？
    ("27", "已经把李四的报告交给领导了"),       # 帮别人完成
    ("28", "小龙的工作票我刚帮他处理掉"),        # 帮别人
    ("29", "这个月事故分析做完了没有"),          # 疑问不是完成
    ("30", "刘主任说他的隐患排查报告要推到下周"),# 推迟=更新
]

print("=" * 90)
print(f"  30 例全链路实测 · 当前用户: {USER}")
print("=" * 90)
print()

for num, text in cases:
    # Step 1: route_intent（正则快速路由）
    intent, intent_data = app.route_intent(text, USER)

    # Step 2: 仅对 intent=add（真正模糊的）走 AI 精细分类
    # update/delete/query 已被正则可靠拦截，不需要 AI 覆盖
    if intent == 'add':
        try:
            ai = app.classify_and_extract(text, '')
            ai_intent = ai.get('intent', 'add')
            intent_data = ai
        except:
            pass

    # Step 3: 提取关键信息
    if intent == 'complete':
        kw = intent_data.get('keyword', '?')
        who = intent_data.get('user_name', USER)

        # 同时用 _extract_completer_name 提取完成人
        completer_raw = app._extract_completer_name(text, USER)
        quoted = app._extract_quoted(text)

        print(f"[{num}] {text}")
        print(f"    意图: complete | 任务名: {kw}")
        print(f"    完成人: {who} | 引号精确: {quoted or '无'}")

    elif intent == 'add':
        name = intent_data.get('name', '?') if isinstance(intent_data, dict) else '?'
        action = intent_data.get('action', text) if isinstance(intent_data, dict) else text
        deadline = intent_data.get('deadline', '') if isinstance(intent_data, dict) else ''
        status = intent_data.get('status', '未完成') if isinstance(intent_data, dict) else '未完成'
        # 代词映射
        if name in ('我','自己','','未知',None):
            name = USER
        print(f"[{num}] {text}")
        print(f"    意图: add | 任务名: {action}")
        print(f"    布置给: {name} | 截止: {deadline or '无'} | 状态: {status}")

    elif intent == 'update':
        sc = intent_data.get('search_condition', text) if isinstance(intent_data, dict) else text
        ns = intent_data.get('new_status', '') if isinstance(intent_data, dict) else ''
        nd = intent_data.get('new_deadline', '') if isinstance(intent_data, dict) else ''
        print(f"[{num}] {text}")
        print(f"    意图: update | 查找条件: {sc}")
        print(f"    新状态: {ns or '不改'} | 新截止: {nd or '不改'}")

    elif intent == 'query':
        q = intent_data.get('question', text) if isinstance(intent_data, dict) else text
        print(f"[{num}] {text}")
        print(f"    意图: query | 问题: {q}")

    elif intent == 'delete':
        dc = intent_data.get('delete_condition', text) if isinstance(intent_data, dict) else text
        print(f"[{num}] {text}")
        print(f"    意图: delete | 条件: {dc}")

    elif intent == 'chat':
        reply = app.chat_directly(text, USER)
        print(f"[{num}] {text}")
        print(f"    意图: chat | 回复: {reply[:60]}...")

    else:
        print(f"[{num}] {text}")
        print(f"    意图: {intent} | 数据: {intent_data}")

    print()
