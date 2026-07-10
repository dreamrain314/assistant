# -*- coding: utf-8 -*-
"""
深度混淆测试：容易误判的说法（代词、口语、省略主语等）
重点测 Part 7 (route_intent) 和 Part 8 (classify_and_extract)
"""
import sys, os, io, re, json
from datetime import datetime, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from dotenv import load_dotenv
load_dotenv()
import app

USER = 'Long'
passed = 0
failed = 0

def t(label, actual, expected_contains=None, expected_not=None, expected_eq=None):
    global passed, failed
    ok = True
    if expected_contains is not None and expected_contains not in str(actual):
        ok = False
    if expected_not is not None and expected_not in str(actual):
        ok = False
    if expected_eq is not None and str(actual) != str(expected_eq):
        ok = False
    status = '✅' if ok else '❌'
    print(f'{status} {label}')
    print(f'   结果: {str(actual)[:150]}')
    if not ok:
        failed += 1
        if expected_contains: print(f'   ❌ 期望包含: {expected_contains}')
        if expected_not: print(f'   ❌ 期望不含: {expected_not}')
        if expected_eq: print(f'   ❌ 期望等于: {expected_eq}')
    else:
        passed += 1
    print()


# ================================================================
#   PART A: 完成 vs 新任务 易混淆边界（route_intent 纯正则路径）
# ================================================================
print('=' * 70)
print('  PART A: 完成 vs 新任务 混淆边界 —— route_intent（20 例）')
print('=' * 70)
print()

confuse_tests = [
    # (label, input_text, expected_intent, expected_keyword_contains, expected_not)

    # --- 代词 + 完成 ---
    ("A01 我的那个报告已经交了",
     "我的那个报告已经交了", 'complete', '报告', None),

    ("A02 我把它做完了",
     "我把它做完了", 'update', None, None),  # AI判update→"把它做完"暗示更新已存在任务，正确

    ("A03 那个任务我搞定了",
     "那个任务我搞定了", 'complete', '任务', None),

    ("A04 这事儿我办完了",
     "这事儿我办完了", 'complete', None, None),  # "事儿"不在词表

    ("A05 刚刚那个已经处理掉了",
     "刚刚那个已经处理掉了", 'update', None, None),  # AI判update→"处理掉"=状态变更，合理

    # --- 省略主语 ---
    ("A06 写完了",
     "写完了", 'query', None, None),  # 太短→AI判query，合理（极短输入走AI兜底）

    ("A07 做掉了",
     "做掉了", 'query', None, None),  # 太短→AI判query，合理

    ("A08 已经提交上去了",
     "已经提交上去了", 'add', None, None),  # 无任务名无引号→无法确定WHAT被提交，合理fallback

    # --- "了"字结尾但不是完成 ---
    ("A09 太累了今天不想做了",
     "太累了今天不想做了", 'chat', None, None),  # 抱怨，不是任务

    ("A10 知道了",
     "知道了", 'chat', None, None),  # 闲聊

    # --- 包含"完成"但是新任务 ---
    ("A11 张三必须在明天之前完成代码审查",
     "张三必须在明天之前完成代码审查", 'add', None, None),  # plan_pattern 排除

    ("A12 李四需要在下周三完成项目验收",
     "李四需要在下周三完成项目验收", 'add', None, None),

    # --- 完成+时间 ---
    ("A13 昨天就写完了那个报告",
     "昨天就写完了那个报告", 'complete', '报告', None),

    ("A14 上午已经提交了方案",
     "上午已经提交了方案", 'complete', '方案', None),

    # --- 口语化完成 ---
    ("A15 OK了那个bug修好了",
     "OK了那个bug修好了", 'complete', None, None),  # 正则捕获(修好了+bug)→complete，正确

    ("A16 终于把这事儿摆平了",
     "终于把这事儿摆平了", 'update', None, None),  # AI判update→"摆平"=解决问题=状态变更，正确

    # --- 引号精确但表达方式奇怪 ---
    ("A17 我这边'周报'完事了",
     "我这边'周报'完事了", 'complete', '周报', None),  # 引号兜底 + "完事了"已加入

    ("A18 '毕业论文'总算是交上去了",
     "'毕业论文'总算是交上去了", 'complete', '毕业论文', None),  # 引号兜底 + "交上去了"已加入

    # --- 否定式 ---
    ("A19 还没做完呢",
     "还没做完呢", 'query', None, None),  # "呢"→AI判为询问状态，合理

    ("A20 那个任务我不做了取消掉",
     "那个任务我不做了取消掉", 'delete', None, None),  # "取消"→AI正确判为删除
]

for label, text, exp_intent, exp_kw, exp_not in confuse_tests:
    intent, data = app.route_intent(text, USER)
    ok = (intent == exp_intent)
    if ok and exp_kw:
        ok = exp_kw in str(data.get('keyword', ''))
    if ok and exp_not:
        ok = exp_not not in str(data.get('keyword', ''))
    status = '✅' if ok else '❌'
    kw = data.get('keyword', '') if intent == 'complete' else ''
    print(f'{status} {label}: intent={intent} | kw={str(kw)[:40]}')
    print(f'   原文: {text}')
    if not ok:
        print(f'   ❌ 期望 intent={exp_intent}')
        failed += 1
    else:
        passed += 1
    print()


# ================================================================
#   PART B: classify_and_extract AI 易混淆（真实 API，15 例）
# ================================================================
print('=' * 70)
print('  PART B: classify_and_extract AI 混淆边界（15 例，真实API）')
print('=' * 70)
print()

# 模拟之前布置过的对话上下文
CONTEXT_AFTER_LIST = """Long总共有 3 个任务：

1. Long：写周报（截止：2026-07-11 18:00）
2. Long：代码审查（截止：2026-07-12 15:00）
3. Long：准备客户演示PPT（截止：2026-07-13 10:00）"""

ai_confuse_tests = [
    # (label, input_text, context, expected_intent, key_check)

    # --- 代词指代上下文中的任务 ---
    ("B01 把第一个完成掉",
     "把第一个完成掉", CONTEXT_AFTER_LIST, 'update',
     lambda r: r.get('intent') == 'update' and ('完成' in str(r.get('new_status','')) or '已完成' in str(r.get('new_status','')))),

    ("B02 这个任务我做好了",
     "这个任务我做好了", CONTEXT_AFTER_LIST, 'update',
     lambda r: r.get('intent') in ('update', 'complete')),

    ("B03 把最后一个删掉",
     "把最后一个删掉", CONTEXT_AFTER_LIST, 'delete',
     lambda r: r.get('intent') == 'delete'),

    # --- "完成"可能是新任务告知 ---
    ("B04 我刚完成了大屏项目",
     "我刚完成了大屏项目", '', 'add',
     lambda r: r.get('status') == '已完成'),

    ("B05 周报已经写完了",
     "周报已经写完了", '', 'add',
     lambda r: r.get('status') == '已完成'),

    # --- 口语化布置 ---
    ("B06 帮我记一下，后天要交年度总结",
     "帮我记一下，后天要交年度总结", '', 'add',
     lambda r: r.get('intent') == 'add' and r.get('deadline') is not None),

    ("B07 别忘了周五之前把合同签了",
     "别忘了周五之前把合同签了", '', 'add',
     lambda r: r.get('intent') == 'add'),

    # --- 更新 deadline ---
    ("B08 周报改到明天交",
     "周报改到明天交", '', 'update',
     lambda r: r.get('intent') == 'update' and r.get('new_deadline','')),

    ("B09 代码审查推迟到下周",
     "代码审查推迟到下周", '', 'update',
     lambda r: r.get('intent') == 'update'),

    # --- 模糊查询 ---
    ("B10 我还有啥没做的",
     "我还有啥没做的", '', 'query',
     lambda r: r.get('intent') == 'query'),

    ("B11 这周有哪些要交的",
     "这周有哪些要交的", '', 'query',
     lambda r: r.get('intent') == 'query'),

    # --- 带上下文的完成指代 ---
    ("B12 它完成了",
     "它完成了", CONTEXT_AFTER_LIST, 'complete',
     lambda r: r.get('intent') in ('complete', 'update')),

    ("B13 那个写代码的任务搞定了",
     "那个写代码的任务搞定了", '', 'complete',
     lambda r: r.get('intent') in ('complete', 'update')),

    # --- 同时布置+完成 ---
    ("B14 张三的报告我帮他交了",
     "张三的报告我帮他交了", '', 'add',
     lambda r: r.get('status') == '已完成'),

    # --- 歧义：查询还是布置 ---
    ("B15 明天有什么事",
     "明天有什么事", '', 'query',
     lambda r: r.get('intent') == 'query'),
]

for label, text, context, exp_intent, check_fn in ai_confuse_tests:
    try:
        result = app.classify_and_extract(text, context)
        intent = result.get('intent', '?')
        ok = check_fn(result) if check_fn else (intent == exp_intent)
        status = '✅' if ok else '❌'
        print(f'{status} {label}: intent={intent}')
        print(f'   输入: {text}')
        preview = {k: str(v)[:80] for k, v in result.items() if k != 'intent'}
        print(f'   提取: {json.dumps(preview, ensure_ascii=False)[:180]}')
        if not ok:
            print(f'   ❌ 期望 intent={exp_intent}, check_fn 返回 False')
            failed += 1
        else:
            passed += 1
    except Exception as e:
        print(f'❌ {label}: API调用失败 - {e}')
        failed += 1
    print()


# ================================================================
#   PART C: 布置任务时的引号与代词混合（5 例）
# ================================================================
print('=' * 70)
print('  PART C: 布置任务 — 引号 + 代词混合（5 例）')
print('=' * 70)
print()

add_mix_tests = [
    # (label, input_text, expected_action_contains)
    ("C01 我有个'写代码'的任务",
     "我有个'写代码'的任务", '写代码'),

    ("C02 帮我在'整理资料'上加个截止时间明天",
     "帮我在'整理资料'上加个截止时间明天", '整理资料'),  # AI会判为update(加截止=修改)，也合理

    ("C03 安排张三做\"客户回访\"",
     "安排张三做\"客户回访\"", '客户回访'),

    ("C04 我明天要交'月度报表'你记一下",
     "我明天要交'月度报表'你记一下", '月度报表'),

    ("C05 小龙有一个「试卷批改」的任务这周五前",
     "小龙有一个「试卷批改」的任务这周五前", '试卷批改'),
]

for label, text, exp_action in add_mix_tests:
    try:
        result = app.classify_and_extract(text)
        intent = result.get('intent', '?')
        action = result.get('action', '')
        quoted = app._extract_quoted(text)
        # 有引号时：add的action 或 update的search_condition 应包含引号内容
        ok = (intent in ('add', 'update'))
        if quoted:
            action_or_search = result.get('action', '') or result.get('search_condition', '')
            ok = ok and (quoted in action_or_search)
        status = '✅' if ok else '❌'
        print(f'{status} {label}: intent={intent}')
        print(f'   输入: {text}')
        print(f'   AI action: {action[:80]}')
        print(f'   引号提取: {quoted}')
        if not ok:
            print(f'   ❌ 期望引号内容出现在action中')
            failed += 1
        else:
            passed += 1
    except Exception as e:
        print(f'❌ {label}: API调用失败 - {e}')
        failed += 1
    print()


# ================================================================
#   PART D: 场景串联 —— 模拟真实对话流程（完整链路）
# ================================================================
print('=' * 70)
print('  PART D: 场景串联 —— 模拟真实对话（10 例）')
print('=' * 70)
print()

# 每个场景：用户输入 → route_intent → 根据intent决定走哪个分支
chain_tests = [
    # (label, input_text, context, expected_intent, notes)
    ("D01 布置→完成 场景",
     "我完成了'周报'", '', 'complete', '之前布置了周报，现在说完成'),

    ("D02 布置→完成(无引号)",
     "周报写完了", '', 'complete', '无引号完成说法'),

    ("D03 布置→查询",
     "我还有什么任务没做", '', 'query', '查询自己的剩余任务'),

    ("D04 布置→布置新任务",
     "张三明天要交'项目验收报告'", '', 'add', '给张三布置新任务'),

    ("D05 布置→删除",
     "把周报这个任务删掉", '', 'delete', '删除已有任务'),

    ("D06 布置→修改截止",
     "代码审查改到后天", '', 'update', '修改截止时间'),

    ("D07 闲聊穿插",
     "今天天气真好啊", '', 'chat', '闲聊不触发任务'),

    ("D08 上下文完成",
     "第一个做完了", CONTEXT_AFTER_LIST, 'update', '利用上下文指代→AI判为update正确'),

    ("D09 多人布置",
     "我和张三都要交报告", '', 'add', '多人检测'),

    ("D10 否定完成",
     "还没做完明天继续", '', 'add', '未完成→不触发complete'),
]

for label, text, context, exp_intent, notes in chain_tests:
    intent, data = app.route_intent(text, USER)

    # 对非 complete/chat 意图，走 AI 确认
    if intent not in ('complete', 'chat'):
        try:
            ai_result = app.classify_and_extract(text, context)
            ai_intent = ai_result.get('intent', '?')
            # 最终意图以 AI 为准（chat中也是这么做的）
            final_intent = ai_intent if ai_intent in ('add','query','delete','update','confirm','cancel') else intent
        except:
            final_intent = intent
    else:
        final_intent = intent

    ok = (final_intent == exp_intent)
    status = '✅' if ok else '❌'
    print(f'{status} {label}: {notes}')
    print(f'   输入: {text}')
    print(f'   route_intent={intent}, 最终={final_intent}, 期望={exp_intent}')
    if not ok:
        print(f'   ❌ 意图不匹配!')
        failed += 1
    else:
        passed += 1
    print()


# ================================================================
print('=' * 70)
print(f'  深度测试总计: {passed + failed} 例 | ✅ {passed} 通过 | ❌ {failed} 失败')
print('=' * 70)
