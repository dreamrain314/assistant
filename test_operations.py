# -*- coding: utf-8 -*-
"""30 例操作层测试：更新/查询/删除 + 完成去重（带真实数据库）"""
import sys, io, json, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from dotenv import load_dotenv; load_dotenv()
import app

USER = '管理员'
TEAM = '默认小组'

print("=" * 80)
print("  操作层深度测试：完成去重 · 更新 · 查询 · 删除")
print("=" * 80)
print()

# ================================================================
# PART A: route_intent 意图路由（20例，纯逻辑）
# ================================================================
print("--- PART A: 意图路由（更新/查询/删除/完成） ---")
print()

tests_a = [
    # 更新类
    ("A01","把张工的报告改到明天交",'update'),
    ("A02","变电站巡检推迟到下周一",'update'),
    ("A03","统计分析的deadline改成这周五",'update'),
    ("A04","标记隐患排查为已完成",'update'),
    # 查询类
    ("A05","张工还有几个任务没做",'query'),
    ("A06","今天截止的有哪些",'query'),
    ("A07","这周的安全检查都完成了吗",'query'),
    # 删除类
    ("A08","删除昨天的临时用电记录",'delete'),
    ("A09","把重复的操作票清掉",'delete'),
    ("A10","取消下周的反事故演练",'delete'),
    # 完成类（无引号，依赖task_words匹配）
    ("A11","安全巡检台账弄好了",'complete'),
    ("A12","那个隐患分析我搞完了",'complete'),
    ("A13","两份工作票都处理掉了",'complete'),
    ("A14","OK了设备维修记录修好了",'complete'),
    # 完成类（不带引号、模糊说法）
    ("A15","这事儿我办完了",'complete'),
    ("A16","昨天提交了安全培训的反馈",'complete'),
    ("A17","操作票已经办妥了",'complete'),
    ("A18","刚刚把那活儿干完了",'complete'),
    # 易与更新混淆
    ("A19","周报还没写呢",'query'),
    ("A20","这个月的安全总结做完了没有",'query'),
]

for label, text, exp in tests_a:
    intent, data = app.route_intent(text, USER)
    ok = (intent == exp)
    s = 'OK' if ok else 'FAIL'
    extra = ''
    if intent == 'complete': extra = f" kw={data.get('keyword','')[:30]}"
    if intent == 'update': extra = f" cond={data.get('search_condition','')[:30]}"
    print(f"[{s}] {label}: {text[:45]}  -> intent={intent}{extra}")
    if not ok: print(f"     *** 期望={exp} 实际={intent}")

print()

# ================================================================
# PART B: handle_complete 去重逻辑（6例，需DB中有数据）
# ================================================================
print("--- PART B: handle_complete 多匹配去重 ---")
print()

# 先看看数据库里有什么任务
team = app.db.get_team(TEAM)
tid = team['id'] if team else None
if tid:
    try:
        r = app.db.supabase.table('records').select('name,action,status,deadline').eq('team_id',tid).neq('status','已完成').order('created_at',desc=True).limit(20).execute()
        tasks = r.data or []
        print(f"  数据库中未完成任务: {len(tasks)} 条")
        for t in tasks[:10]:
            print(f"    · {t.get('name','?')}: {t.get('action','?')} (截止:{t.get('deadline','无')})")
    except Exception as e:
        print(f"  查询失败: {e}")
        tasks = []
else:
    tasks = []
print()

# 用实际数据库中的任务来测试完成匹配
if tasks:
    # 测试1: 精确匹配已存在的任务
    test_task = tasks[0]
    test_kw = test_task.get('action','')[:4]
    test_name = test_task.get('name', USER)
    print(f"  B01 精确匹配: handle_complete('{test_kw}', '{test_name}')")
    result, _ = app.handle_complete(test_kw, test_name, TEAM)
    print(f"    -> {str(result.get('result',''))[:120]}")
    print()

    # 测试2: 用模糊说法匹配
    if len(tasks) >= 2:
        t2 = tasks[1]
        kw2 = t2.get('action','')[:3]
        n2 = t2.get('name', USER)
        print(f"  B02 模糊匹配: handle_complete('{kw2}', '{n2}')")
        result2, _ = app.handle_complete(kw2, n2, TEAM)
        print(f"    -> {str(result2.get('result',''))[:120]}")
        print()

# 测试3: 搜索不存在的任务（应返回"没找到"）
print(f"  B03 无匹配: handle_complete('不存在的任务XYZ', '{USER}')")
result3, _ = app.handle_complete('不存在的任务XYZ', USER, TEAM)
print(f"    -> {str(result3.get('result',''))[:120]}")
print()

# 测试4: 跨用户搜索——当自己的任务中找不到时，应该搜索全组
# 先看看有没有别人的任务
if tasks:
    others = [t for t in tasks if t.get('name','') != USER]
    if others:
        ot = others[0]
        okw = ot.get('action','')[:4]
        oname = ot.get('name','?')
        print(f"  B04 跨用户完成: handle_complete('{okw}', '{USER}') — 任务是{oname}的")
        print(f"     (当前用户={USER}，任务属于{oname}，看能否找到)")
        result4, _ = app.handle_complete(okw, USER, TEAM)
        print(f"    -> {str(result4.get('result',''))[:150]}")
        print()

# ================================================================
# PART C: do_query 查询逻辑（5例）
# ================================================================
print("--- PART C: do_query 查询 ---")
print()

query_tests = [
    ("C01","今天有哪些任务"),
    ("C02","管理员的任务"),
    ("C03","所有未完成的任务"),
    ("C04","这周截止的任务"),
    ("C05","安全相关的任务"),
]
for label, q in query_tests:
    try:
        result = app.do_query(q, USER, TEAM)
        if isinstance(result, tuple): result = result[0]
        count = result.get('count', '?')
        preview = str(result.get('result',''))[:100].replace('\n',' / ')
        print(f"  [{label}] {q} -> {count}条")
        print(f"    {preview}")
    except Exception as e:
        print(f"  [{label}] {q} -> 出错: {e}")
    print()

# ================================================================
# PART D: do_delete / do_update 操作（5例）
# ================================================================
print("--- PART D: 删除/更新 ---")
print()

# 删除测试
print("  D01 do_delete('不存在的任务'):")
r_del = app.do_delete('不存在的任务XYZ', TEAM)
print(f"    -> {str(r_del)[:120]}")
print()

if tasks:
    t_del = tasks[0]
    del_kw = t_del.get('action','')[:6]
    print(f"  D02 do_delete('{del_kw}'):")
    r_del2 = app.do_delete(del_kw, TEAM)
    print(f"    -> {str(r_del2)[:200]}")
    print()

# 更新测试
print("  D03 do_update('不存在的任务', '已完成'):")
r_upd = app.do_update('不存在的任务XYZ', '已完成')
print(f"    -> {str(r_upd)[:120]}")
print()

if tasks:
    t_upd = tasks[0]
    upd_kw = t_upd.get('action','')[:6]
    print(f"  D04 do_update('{upd_kw}', '进行中'):")
    r_upd2 = app.do_update(upd_kw, '进行中')
    print(f"    -> {str(r_upd2)[:120]}")
    # 改回来
    app.do_update(upd_kw, '未完成')
    print()

print("=" * 80)
print("  测试完成")
print("=" * 80)
