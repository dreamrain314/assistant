# -*- coding: utf-8 -*-
"""200 cases - direct function calls (fast, no HTTP)"""
import sys,io,time
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
from dotenv import load_dotenv; load_dotenv()
from app import route_intent, classify_and_extract, chat_directly

ADMIN='管理员'; ZS='张三'; LS='李四'
passed=0; failed=0; issues=[]

def T(label, text, user, exp_intent):
    global passed,failed
    intent, data = route_intent(text, user)
    if intent not in ('complete','chat','update','delete','query'):
        try:
            ai = classify_and_extract(text, '')
            ai_i = ai.get('intent', intent)
            if ai_i in ('add','query','delete','update','confirm','cancel'):
                intent = ai_i; data = ai
        except: pass
    ok = (intent == exp_intent)
    if ok: passed += 1
    else:
        failed += 1
        kw = data.get('keyword','') if intent=='complete' else ''
        issues.append((label, text, user, exp_intent, intent, kw))
    return ok

TOTAL = 200
now = time.time()

# ========== 30 complete (admin helps others + self) ==========
for i,(t,u) in enumerate([
('张三的工作报告已经交了',ADMIN),('李四的代码审查我帮他做好了',ADMIN),
('王五的安全巡检我替他搞定了',ADMIN),('小龙的隐患排查台账帮忙弄完了',ADMIN),
('小红那份统计月报我替她交上去了',ADMIN),('老张的操作票我帮他办妥了',ADMIN),
('赵工的接地测试替他处理掉了',ADMIN),('刘主任那份安全总结帮他提交了',ADMIN),
('小周的反事故演练方案我帮他搞完了',ADMIN),('老王的维保记录我刚替他弄好',ADMIN),
('两份工作票都办完了',ADMIN),('昨天搞定了安全培训记录',ADMIN),
('OK了那个设备台账已经修好了',ADMIN),('刚刚把那活儿干完了',ADMIN),
('这事儿我办完了',ADMIN),('继保测试数据已经提交了',ADMIN),
('带电检测的报告处理掉了',ADMIN),('隐患整改通知单交上去了',ADMIN),
('安全活动记录弄好了',ADMIN),('倒闸操作票已经办妥',ADMIN),
('刚把小龙的活干了',ADMIN),('这活儿已经摆平了',ADMIN),
('安全隐患那事儿处理掉了',ADMIN),('那个bug已经修好了',ADMIN),
('刚刚那任务搞定了',ADMIN),('把这事儿给办了',ADMIN),
('客户演示我已经交掉了',ADMIN),('那份报告我弄好了',ADMIN),
('王五的台账我替他更新了',ADMIN),('把老张的任务做掉了',ADMIN),
]): T(f'A{i+1:02d}',t,u,'complete')

# ========== 25 add (manager assigns) ==========
for i,(t,u) in enumerate([
('张工明天完成变电站接地测试报告',ADMIN),('安排李工周五前写完安全评估方案',ADMIN),
('王主任需要提交一季度事故统计分析',ADMIN),('赵工有一个配电线路检修台账要更新后天截止',ADMIN),
('让小龙下周一之前完成绝缘耐压试验',ADMIN),('提醒老张这周五交安全巡检月报',ADMIN),
('给老王布置有限空间作业安全培训任务',ADMIN),('要求刘主任本周内提交两票三制执行统计',ADMIN),
('下周安全生产例会纪要由小红来写',ADMIN),('安排一次全站继保装置定检明天开始',ADMIN),
('明天要完成年度供电可靠性统计',ADMIN),('我需要在下周三前写好安全工作总结',ADMIN),
('帮我记一下后天要交安全生产月报',ADMIN),('别忘了这周五之前把隐患排查汇总交了',ADMIN),
('临时用电审批要在这周内批完',ADMIN),('下周安排全部门反事故演练',ADMIN),
('安规考试成绩汇总今天必须做出来',ADMIN),('让各班组提交上半年安全培训记录',ADMIN),
('接地电阻测试数据需在下周前录入系统',ADMIN),('安排明天上午的倒闸操作任务',ADMIN),
('布置一个变电站巡检下周完成',ADMIN),('需要有人写一份安全月报',ADMIN),
('通知大家明天有安全培训',ADMIN),('让小龙和老王一起完成配电检查',ADMIN),
('安排一个紧急的隐患整改任务',ADMIN),
]): T(f'B{i+1:02d}',t,u,'add')

# ========== 30 query ==========
for i,(t,u) in enumerate([
('今天有哪些任务',ADMIN),('张工还有几个没完成',ADMIN),
('这周安全检测相关的任务有哪些',ADMIN),('所有未完成任务列出来',ADMIN),
('明天截止的有哪些',ADMIN),('王五的任务有哪些',ADMIN),
('隐患排查相关的任务这周有几个',ADMIN),('谁有超时的任务',ADMIN),
('小龙还有多少工作没做完',ADMIN),('已完成的任务有哪些',ADMIN),
('统计各人还有几个未完成',ADMIN),('这个月工作票执行情况',ADMIN),
('上周布置的都完成了吗',ADMIN),('展示所有人的任务',ADMIN),
('安全培训相关任务还有哪些没做',ADMIN),('本月事故分析报告谁还没交',ADMIN),
('这周有什么安排',ADMIN),('下周截止的任务',ADMIN),
('我还有什么任务没完成',ADMIN),('有哪些任务是进行中的',ADMIN),
('统计各部门完成率',ADMIN),('谁的任务最多',ADMIN),
('最近一周新增的任务',ADMIN),('有哪些任务已经超时三天以上',ADMIN),
('各班组任务分布情况',ADMIN),('今天要截止的是什么',ADMIN),
('帮我查一下所有未完成',ADMIN),('有没有今天过期的',ADMIN),
('显示本周需完成的工作',ADMIN),('找我布置的所有任务',ADMIN),
]): T(f'C{i+1:02d}',t,u,'query')

# ========== 25 update ==========
for i,(t,u) in enumerate([
('把张工的接地测试改到下周一交',ADMIN),('变电站巡检报告推迟到明天',ADMIN),
('隐患整改台账标记为已完成',ADMIN),('统计分析报告deadline改成这周五',ADMIN),
('王五的代码审查提前到明天下午',ADMIN),('安全培训记录改成进行中',ADMIN),
('小红那份报告改到后天交',ADMIN),('把老张的操作票往后推三天',ADMIN),
('刘主任要把他那份统计推到下周',ADMIN),('把小龙的试卷延期到周五',ADMIN),
('修改赵工截止时间为大后天',ADMIN),('标记接地测试为已完成',ADMIN),
('把安全培训推迟到下月',ADMIN),('把周报截止时间提前到今天',ADMIN),
('标记所有巡检为已完成',ADMIN),('把我的任务延期到下周',ADMIN),
('改成下周三交',ADMIN),('把这个标记为进行中',ADMIN),
('更新截止时间为明天下午',ADMIN),('把报告改成已完成状态',ADMIN),
('推到月底',ADMIN),('提前到这周五',ADMIN),
('deadline改成后天',ADMIN),('全部标记已完成',ADMIN),
('延后三天',ADMIN),
]): T(f'D{i+1:02d}',t,u,'update')

# ========== 15 delete ==========
for i,(t,u) in enumerate([
('删掉上周临时用电审批记录',ADMIN),('把重复的操作票清掉',ADMIN),
('取消下周反事故演练',ADMIN),('移除所有已完成的隐患排查',ADMIN),
('删除过期的工作票',ADMIN),('清空所有测试数据',ADMIN),
('取消王五的倒闸操作',ADMIN),('删除李四那条重复的代码审查',ADMIN),
('取消全部过期任务',ADMIN),('删除去年的归档任务',ADMIN),
('把这条删了',ADMIN),('清除那些测试数据',ADMIN),
('删掉这条重复的',ADMIN),('这个任务不要了去掉',ADMIN),
('移除完成的任务',ADMIN),
]): T(f'E{i+1:02d}',t,u,'delete')

# ========== 20 confuse/chat (manager) ==========
for i,(t,u,e) in enumerate([
('那个写代码的任务搞定了',ADMIN,'complete'),('我这边工作票完事了',ADMIN,'complete'),
('周报还没写呢',ADMIN,'query'),('这个月安全总结做完了没有',ADMIN,'query'),
('安全检查都完成了吗',ADMIN,'query'),('帮我看下谁还没交月报',ADMIN,'query'),
('那份合同审批完了没',ADMIN,'query'),('把该清的都清掉',ADMIN,'delete'),
('差不多都完事了就剩一个',ADMIN,'chat'),('没啥事我先走了',ADMIN,'chat'),
('收到马上处理',ADMIN,'chat'),('今天真忙啊',ADMIN,'chat'),
('辛苦了大家',ADMIN,'chat'),('帮忙看看还有啥漏掉的',ADMIN,'query'),
('干完了都干完了',ADMIN,'complete'),('这周效率不错',ADMIN,'chat'),
('快点把剩余的搞定',ADMIN,'add'),('领导来检查了注意',ADMIN,'chat'),
('大家辛苦了早点休息',ADMIN,'chat'),('别忘了明天开会',ADMIN,'chat'),
]): T(f'F{i+1:02d}',t,u,e)

# ========== 25 employee complete own ==========
for i,(t,u) in enumerate([
('我的工作报告写完了',ZS),('安全隐患排查我已经做好了',ZS),
('操作票搞定了',ZS),('巡检记录提交了',ZS),
('安全培训那事儿我办妥了',ZS),('统计报表交上去了',ZS),
('接地测试我弄好了',ZS),('倒闸操作已经处理掉了',ZS),
('安全活动记录修好了',ZS),('那份维保记录我搞完了',ZS),
('刚刚把台账更新了',ZS),('事故分析报告已经交掉了',ZS),
('月报昨晚上传了',ZS),('应急预案演练记录做完了',ZS),
('两票统计搞定了已经',ZS),('今天工作票都办完了',ZS),
('代码审查已经提交',ZS),('设备检修报告写好了',ZS),
('安全巡检数据都弄好了',ZS),('有限空间作业审批我搞定了',ZS),
('我的事做完了',ZS),('全都好了已经',ZS),
('我那份报告交了',ZS),('今天任务完成了',ZS),
('还有一份没弄完',ZS),
]): T(f'G{i+1:02d}',t,u,'complete')

# ========== 15 employee add for self ==========
for i,(t,u) in enumerate([
('我明天要交安全巡检月报',ZS),('帮我记后天要交安全生产总结',ZS),
('这周五必须做完隐患排查台账',ZS),('下周我需要完成继保测试',ZS),
('我要在月底前交年度统计报告',ZS),('别忘了提醒我明天交操作票',ZS),
('给自己安排安全培训任务',ZS),('明天下班前要完成接地电阻测试',ZS),
('这个月还有一份事故分析没写',ZS),('下午要做完变电站巡检记录',ZS),
('下周把设备维修台账整理好',ZS),('周日之前提交周报',ZS),
('八月十五号前完成安全评估',ZS),('后天有一份绝缘测试要做',ZS),
('月底交供电可靠性统计',ZS),
]): T(f'H{i+1:02d}',t,u,'add')

# ========== 15 employee query ==========
for i,(t,u) in enumerate([
('我还有什么任务没做',ZS),('今天我要做什么',ZS),
('这周我有哪些任务',ZS),('明天截止的还有几个',ZS),
('超时的有哪些',ZS),('我已经完成了多少',ZS),
('还有什么事没做完',ZS),('帮我查这个月我完成了哪些',ZS),
('我的隐患排查做完了没有',ZS),('最近有什么新任务吗',ZS),
('统计我的完成情况',ZS),('看看我的工作进度',ZS),
('我还有几份报告没交',ZS),('查下我的任务',ZS),
('今天有什么要做的',ZS),
]): T(f'I{i+1:02d}',t,u,'query')

elapsed = time.time() - now
print()
print('='*70)
print(f'  {TOTAL} 例实测完成: OK {passed} | FAIL {failed} | {elapsed:.0f}s')
if issues:
    print(f'  发现 {len(issues)} 个问题:')
    for lbl,txt,usr,exp,act,kw in issues:
        print(f'    [{lbl}] {usr}: {txt[:40]} -> expect={exp} actual={act} kw={kw[:20]}')
print('='*70)
