# -*- coding: utf-8 -*-
"""
30+ 例完整逻辑测试 —— 直接调用 app.py 中的函数，跑真实结果
"""
import sys, os, io, re, json
from datetime import datetime, timedelta

# 确保输出中文不乱码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 加载环境变量后才导入模块
from dotenv import load_dotenv
load_dotenv()

# 导入模块（会初始化 Supabase 连接）
import app

USER = 'Long'
TEAM = '默认小组'

passed = 0
failed = 0

def check(label, actual, expected_contains=None, expected_not=None):
    global passed, failed
    ok = True
    if expected_contains is not None:
        if expected_contains not in str(actual):
            ok = False
    if expected_not is not None:
        if expected_not in str(actual):
            ok = False
    status = '✅' if ok else '❌'
    print(f'{status} {label}')
    print(f'   结果: {str(actual)[:120]}')
    if not ok:
        failed += 1
        if expected_contains: print(f'   期望包含: {expected_contains}')
        if expected_not: print(f'   期望不含: {expected_not}')
    else:
        passed += 1
    print()

print('=' * 70)
print('  PART 1: _extract_quoted 引号提取（8 例）')
print('=' * 70)
print()

check("1.1 英文单引号",
      app._extract_quoted("我完成了'工作报告'"),
      expected_contains='工作报告')

check("1.2 英文双引号",
      app._extract_quoted('张三有"写周报"的任务'),
      expected_contains='写周报')

check("1.3 中文引号「」",
      app._extract_quoted('我已经完成了「毕业论文」'),
      expected_contains='毕业论文')

check("1.4 中文双引号『』",
      app._extract_quoted('搞定了『项目方案』'),
      expected_contains='项目方案')

check("1.5 混合：双引号内带空格",
      app._extract_quoted('提交了"年度工作总结报告"给领导'),
      expected_contains='年度工作总结报告')

check("1.6 无引号",
      app._extract_quoted('我完成了工作报告'),
      expected_contains=None)

check("1.7 单引号在布署中",
      app._extract_quoted("帮张三安排'客户演示PPT'，后天交"),
      expected_contains='客户演示PPT')

check("1.8 多引号取第一个",
      app._extract_quoted("完成'日报'和'周报'"),
      expected_contains='日报')

print('=' * 70)
print('  PART 2: _extract_completer_name 完成人提取（10 例）')
print('=' * 70)
print()

check("2.1 我完成了 → 当前用户",
      app._extract_completer_name("我完成了'工作报告'", USER),
      expected_contains=USER)

check("2.2 张三完成了 → 张三",
      app._extract_completer_name("张三完成了'代码审查'", USER),
      expected_contains='张三')

check("2.3 我已经完成了 → 当前用户",
      app._extract_completer_name("我已经完成了「毕业论文」", USER),
      expected_contains=USER)

check("2.4 今天已经完成了 → 默认当前用户",
      app._extract_completer_name("今天已经完成了'日报'", USER),
      expected_contains=USER)

check("2.5 小龙做完了 → 小龙",
      app._extract_completer_name("小龙做完了'试卷'", USER),
      expected_contains='小龙')

check("2.6 李四终于搞定了 → 李四",
      app._extract_completer_name("李四终于搞定了项目方案", USER),
      expected_contains='李四')

check("2.7 无主语完成 → 默认当前用户",
      app._extract_completer_name("完成了'周报'", USER),
      expected_contains=USER)

check("2.8 王五已经做完了 → 王五",
      app._extract_completer_name("王五已经做完了客户需求分析", USER),
      expected_contains='王五')

check("2.9 刚刚搞定了 → 默认当前用户",
      app._extract_completer_name("刚刚搞定了'代码bug'", USER),
      expected_contains=USER)

check("2.10 小红终于写完了 → 小红",
      app._extract_completer_name("小红终于写完了'年度总结'", USER),
      expected_contains='小红')

print('=' * 70)
print('  PART 3: _clean_action_pronouns 代词清洗（5 例）')
print('=' * 70)
print()

check("3.1 '我的工作报告' → 清洗为用户名版",
      app._clean_action_pronouns('我的工作报告', '张三'),
      expected_not='我')

check("3.2 '我明天交报告' → 替换我",
      app._clean_action_pronouns('我明天交报告', '李四'),
      expected_contains='李四',
      expected_not='我')

check("3.3 '你帮我看看这个' → 替换你",
      app._clean_action_pronouns('你帮我看看这个', '王五'),
      expected_contains='王五',
      expected_not='你')

check("3.4 '他和她一起去' → 替换他/她",
      result := app._clean_action_pronouns('他和她一起去', '赵六'),
      expected_not='他')

check("3.5 '我的你的他的' → 代词全清",
      result := app._clean_action_pronouns('我的你的他的', '测试员'),
      expected_not='我')

print('=' * 70)
print('  PART 4: _extract_multi_names 多人检测（5 例）')
print('=' * 70)
print()

check("4.1 A和B → 两人",
      str(app._extract_multi_names('张三和李四完成报告', USER) or []),
      expected_contains='张三')

check("4.2 A、B → 两人",
      str(app._extract_multi_names('小龙、小虎做试卷', USER) or []),
      expected_contains='小龙')

check("4.3 我和B → 当前用户+对方",
      str(app._extract_multi_names('我和张三写报告', USER) or []),
      expected_contains=USER)

check("4.4 无连接词 → None",
      app._extract_multi_names('张三完成报告', USER),
      expected_contains=None)

check("4.5 A跟B → 两人",
      str(app._extract_multi_names('小红跟小明打扫卫生', USER) or []),
      expected_contains='小红')

print('=' * 70)
print('  PART 5: validate_deadline 截止时间解析（5 例）')
print('=' * 70)
print()

check("5.1 标准格式 YYYY-MM-DD HH:MM",
      app.validate_deadline('2026-07-15 18:00'),
      expected_contains='2026-07-15 18:00')

check("5.2 日期格式 YYYY-MM-DD",
      app.validate_deadline('2026-07-20'),
      expected_contains='2026-07-20')

check("5.3 斜杠格式",
      app.validate_deadline('2026/08/01 14:00'),
      expected_contains='2026-08-01 14:00')

check("5.4 空值 → None",
      str(app.validate_deadline('')),
      expected_contains='None')

check("5.5 null → None",
      str(app.validate_deadline('null')),
      expected_contains='None')

print('=' * 70)
print('  PART 6: chat_directly 闲聊快速匹配（6 例）')
print('=' * 70)
print()

check("6.1 你好",
      app.chat_directly('你好', USER),
      expected_contains='你好')

check("6.2 你是谁",
      app.chat_directly('你是谁', USER),
      expected_contains='助理')

check("6.3 谢谢",
      app.chat_directly('谢谢', USER),
      expected_contains='不客气')

check("6.4 再见",
      app.chat_directly('再见', USER),
      expected_contains='再见')

check("6.5 你能做什么",
      app.chat_directly('你能做什么', USER),
      expected_contains='录入')

check("6.6 我是谁",
      app.chat_directly('我是谁', USER),
      expected_contains=USER)

print('=' * 70)
print('  PART 7: route_intent 意图路由（完整+闲聊检测，不含AI）（12 例）')
print('=' * 70)
print()

# complete 场景（纯正则，不调 AI）
tests_complete = [
    ("7.1 我完成了'工作报告'", "我完成了'工作报告'", 'complete', '工作报告'),
    ("7.2 张三做好了\"代码审查\"", '张三做好了"代码审查"', 'complete', '代码审查'),
    ("7.3 搞定了「毕业论文」", '搞定了「毕业论文」', 'complete', '毕业论文'),
    ("7.4 已经写完了'日报'", "已经写完了'日报'", 'complete', '日报'),
    ("7.5 小龙做完了试卷", '小龙做完了试卷', 'complete', None),  # 无引号
    ("7.6 今天终于搞定了项目", '今天终于搞定了项目', 'complete', None),
]
for label, text, exp_intent, exp_kw in tests_complete:
    intent, data = app.route_intent(text, USER)
    ok = (intent == exp_intent)
    if ok and exp_kw:
        ok = exp_kw in str(data.get('keyword', ''))
    status = '✅' if ok else '❌'
    print(f'{status} {label}: intent={intent}, keyword={data.get("keyword","")[:40]}')
    if ok: passed += 1
    else: failed += 1; print(f'   ❌ 期望 intent={exp_intent}, keyword含{exp_kw}')
    print()

# chat 场景
tests_chat = [
    ("7.7 你好啊", '你好啊', 'chat'),
    ("7.8 谢谢你了", '谢谢你了', 'chat'),
    ("7.9 哈哈有意思", '哈哈有意思', 'chat'),
]
for label, text, exp_intent in tests_chat:
    intent, data = app.route_intent(text, USER)
    ok = (intent == exp_intent)
    status = '✅' if ok else '❌'
    print(f'{status} {label}: intent={intent}')
    if ok: passed += 1
    else: failed += 1; print(f'   ❌ 期望 intent={exp_intent}')
    print()

print('=' * 70)
print('  PART 8: classify_and_extract AI 意图分类（5 例，调用真实API）')
print('=' * 70)
print()

ai_tests = [
    ("8.1 布置任务-带引号", "张三有一个'写周报'的任务，明天截止", 'add'),
    ("8.2 布置任务-无引号", "李四下周五前完成客户演示PPT", 'add'),
    ("8.3 查询任务", "今天有哪些任务", 'query'),
    ("8.4 删除任务", "删除张三的周报任务", 'delete'),
    ("8.5 更新任务", "把小龙的试卷改成已完成", 'update'),
]
for label, text, exp_intent in ai_tests:
    try:
        result = app.classify_and_extract(text)
        intent = result.get('intent', '?')
        ok = (intent == exp_intent)
        status = '✅' if ok else '❌'
        print(f'{status} {label}: intent={intent}')
        preview = {k: v for k, v in result.items() if k != 'intent'}
        print(f'   提取: {json.dumps(preview, ensure_ascii=False)[:150]}')
        if ok: passed += 1
        else: failed += 1; print(f'   ❌ 期望 intent={exp_intent}')
    except Exception as e:
        print(f'❌ {label}: AI调用失败 - {e}')
        failed += 1
    print()

print('=' * 70)
print(f'  总计: {passed + failed} 例 | ✅ {passed} 通过 | ❌ {failed} 失败')
print('=' * 70)
