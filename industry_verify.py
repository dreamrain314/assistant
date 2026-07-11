# -*- coding: utf-8 -*-
"""
国家电力集团 · 安全检测部门 · 任务助理 · 意图逻辑验证脚本
============================================================
用途: 复制给其他 AI 独立运行，交叉验证意图判断。
运行: python industry_verify.py
输出: industry_report_<timestamp>.txt
"""
import re, os
from datetime import datetime

REPORT_FILE = f"industry_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
log_lines = []
USER = '__CURRENT_USER__'

def log(s):
    try: print(s)
    except: pass
    log_lines.append(s)

# ================================================================
#  核心逻辑 —— 与 app.py 完全一致
# ================================================================

def _extract_quoted(text):
    for pat in [r'"([^"]+)"', r"'([^']+)'", r'「([^」]+)」', r'『([^』]+)』']:
        m = re.search(pat, text)
        if m: return m.group(1).strip()
    return None

def _extract_completer_name(text, current_user):
    """从 XX完成了/做完了 中提取完成人。无明确人名 → current_user（宁可回退也不乱猜）"""
    m = re.search(
        r'(完成了|做好了|搞定了|写完了|做完了|提交了|结束了|办完了|弄完了|干完了|交完了|'
        r'弄好了|写好了|办好了|做好了|干好了|处理掉了|处理完了|修好了|修完了|完事了|'
        r'交上去了|清掉了|搞完了)'
        r'|(完成|做好|搞定|写完|做完|提交|结束|办完|弄完|干完|交完|弄好|写好|办好|做好|干好|'
        r'处理掉|修好|完事|交上|清掉|搞完)\\b',
        text)
    if not m: return current_user
    before = text[:m.start()].strip()
    adverbs = ['已经','早就','刚刚','才','终于','今天','昨天','明天','后天',
               '上午','下午','晚上','都','就','也','全','全部','基本上']
    changed = True
    while changed:
        changed = False
        for adv in adverbs:
            if before.endswith(adv):
                before = before[:-len(adv)].strip()
                changed = True
    if not before: return current_user
    name_m = re.search(r'(\S{1,4})$', before)
    if not name_m: return current_user
    name = name_m.group(1)
    if name.endswith('我'): return current_user
    if name in ('我','自己','','把','将','的','了','被','让','给','和','与'):
        return current_user
    if len(name) == 1 and len(before) > 5: return current_user
    measure_words = set('份张个条项次台套批件颗块段本支只双对群些点种类样位名间座辆艘架篇幅首篇封则门堂场遍趟回下顿阵')
    if name[0] in measure_words: return current_user
    task_like = ['报告','记录','数据','台账','工作票','操作票','通知','方案',
                 '总结','报表','统计','分析','日志','测试','检查','检测',
                 '巡检','演练','培训','审批','验收','整改','维修','维保',
                 '工作','任务','试卷','作业','项目','文档','合同','预案',
                 '简报','快报','季报','年报','月报','周报','日报','论文',
                 '指标','评分','考核','反馈','隐患','事故','故障','调度',
                 '票','单','表','书','稿','图','件','录','据']
    if name in task_like: return current_user
    common_surnames = set('王李张刘陈杨黄赵周吴徐孙马胡朱郭何罗高林郑梁谢唐许冯宋韩邓彭曹曾田董潘袁蔡蒋余于杜叶程魏苏吕丁任卢姚钟姜崔谭陆范汪廖石金贾韦夏傅方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴莫孔向汤')
    if len(before) > 8 and len(name) >= 1 and name[0] not in common_surnames:
        return current_user
    name = re.sub(r'[的了]$', '', name)
    return name if name else current_user

def route_intent(user_input, user_name):
    ui = user_input.strip()

    plan_patterns = [
        '要.*做完','要.*完成','需要.*完成','得.*做完','必须.*完',
        '计划.*完','打算.*完','准备.*完','应该.*完','要求.*完',
        '希望.*完','想.*做完','争取.*完','预计.*完','安排.*做',
        '布置.*任务','有一个.*任务','有一个.*工作','有.*要做',
    ]
    is_plan = any(re.search(p, ui) for p in plan_patterns)
    if not is_plan:
        complete_keywords = [
            '完成了','做好了','搞定了','写完了','做完了','已经.*了',
            '提交了','结束了','办完了','办妥了','弄完了','干完了',
            '交完了','完成了的','已做完','已写好','已提交','已搞定',
            '全部.*完','都.*完了','就.*完了','终于.*完了',
            '处理掉了','处理完了','修好了','修完了',
            '完事了','完事儿','交上去了','交上了','交掉了',
            '做掉了','弄好了','清掉了','搞完了','搞掉了',
        ]
        task_words = [
            '任务','试卷','报告','作业','项目','工作','事情',
            '题目','文档','方案','计划书','报表','总结','汇报',
            '日报','周报','月报','论文','代码','PPT','演示','合同',
            '申请','审批','会议','纪要','邮件','通知','公告',
            '翻译','调研','分析','评估','预算','报销','采购',
            '培训','考核','绩效','预案','脚本','画图','海报',
            '视频','原型','计划','需求','复盘','总结',
            '事儿','活','活儿','bug','Bug','BUG',
            '安全','检测','巡检','隐患','排查','事故','故障','风险',
            '整改','验收','监测','维保','维修','保养','台账',
            '调度','值班','交接班','日志','运行','设备','线路',
            '变电站','配电','输电','发电','供电','停电','送电',
            '倒闸','带电','接地','绝缘','耐压','继保','计量',
            '应急预案','演练','反事故','安全培训','安规','两票',
            '工作票','操作票','动火','高空','有限空间','临时用电',
            '反馈','统计','数据','指标','对标','考核表','评分',
            '季报','年报','快报','简报','通报','函','请示',
        ]
        if re.search(r'(?:完了|好了|定了|交了|掉了)\s*(?:没有|了吗|没呢|没啊|没|不)\s*$', ui):
            return 'query', {'question': ui}
        ck_match = any(re.search(kw, ui) for kw in complete_keywords)
        tw_match = any(tw in ui for tw in task_words)
        if ck_match and (tw_match or bool(_extract_quoted(ui))):
            completer = _extract_completer_name(ui, user_name)
            quoted = _extract_quoted(ui)
            if quoted:
                return 'complete', {'keyword': quoted, 'user_name': completer}
            kw = ui
            for remove in ['已经','了','完成','做好','搞定','写完','做完','提交','结束','办完','我的','你的','他的','她的','这个','那个','把']:
                kw = kw.replace(remove, '')
            kw = kw.replace('我', completer)
            kw = kw.replace('你', completer)
            kw = re.sub(r'^[的了吗呢啊着过吧嘿哦哈呀]+', '', kw).strip()[:30]
            return 'complete', {'keyword': kw or ui[:30], 'user_name': completer}

    chat_patterns = [
        '你好','hi','hello','嗨','在吗','在不在','哈啰',
        '你是谁','你叫什么','你能做什么','你有什么功能','你会什么','你能干啥',
        '我是谁','我叫什么','我的名字','我叫啥',
        '谢谢','感谢','多谢','3q','thx','辛苦','麻烦了',
        '再见','拜拜','bye','晚安','明天见','回见','88',
        '哈哈','嘿嘿','嗯嗯','知道了','好的','ok','嗯','哦',
        '今天天气','讲个笑话','聊聊天','无聊','放松','休息',
        '吃饭','睡觉','累了','困了','好累','好困',
    ]
    for p in chat_patterns:
        if p in ui: return 'chat', {}

    if any(kw in ui for kw in ('吗','呢','什么','哪些','怎么','如何','谁','几个','多少')):
        return 'query', {'question': ui}

    update_patterns = [
        '改到','推迟','提前','延期','改成','标记为','状态.*改','截止.*改',
        'deadline.*改','改成.*完成','标记.*完成','推到','推后','往后推',
    ]
    if any(re.search(p, ui) for p in update_patterns):
        return 'update', {'search_condition': ui}

    if any(kw in ui for kw in ('删掉','删除','清空','清除','去掉','移除','取消')):
        return 'delete', {'delete_condition': ui}

    return 'add', {}

# ================================================================
# 50 例测试
# ================================================================
TESTS = []
def T(label, text, expected_intent, notes=''):
    TESTS.append((label, text, expected_intent, notes))

T("C01", "我完成了'安全巡检报告'", 'complete')
T("C02", "隐患排查台账已经写完了", 'complete')
T("C03", "整改通知单交上去了", 'complete')
T("C04", "昨天就搞定了安全培训记录", 'complete')
T("C05", "两份工作票都办完了", 'complete')
T("C06", "继保测试数据已经提交了", 'complete')
T("C07", "安全活动记录弄好了", 'complete')
T("C08", "带电检测的数据分析处理掉了", 'complete')
T("C09", "完成了'两票三制'执行情况统计", 'complete')
T("C10", "倒闸操作记录已经办妥了", 'complete')
T("A01", "王工周五前完成'变电站接地电阻测试报告'", 'add')
T("A02", "张工明天要交绝缘耐压试验数据", 'add')
T("A03", "安排李工进行有限空间作业安全培训", 'add')
T("A04", "下周必须完成年度安全工作总结", 'add')
T("A05", "刘主任要求各班组提交一季度事故统计分析", 'add')
T("A06", "安排下周的反事故演练方案", 'add')
T("A07", "配电线路故障检修台账需要更新", 'add')
T("A08", "年度供电可靠性指标统计月底前完成", 'add')
T("A09", "国网安规考试的成绩汇总今天要做出来", 'add')
T("A10", "临时用电审批单明天下午前要批完", 'add')
T("Q01", "今天有哪些安全检测任务", 'query')
T("Q02", "张工还有几个隐患整改没完成", 'query')
T("Q03", "本周的巡检报告都交了吗", 'query')
T("Q04", "哪些工作票快到期了", 'query')
T("Q05", "输电线路巡视记录要做完了吗", 'query')
T("U01", "变电站巡检报告改到下周一交", 'update')
T("U02", "安全培训记录改成已完成", 'update')
T("U03", "隐患整改台账的截止时间提前到明天", 'update')
T("U04", "统计分析报告标记为已完成", 'update')
T("U05", "接地电阻测试推迟到大后天", 'update')
T("U06", "王工说他的隐患排查报告要推到下周", 'update')
T("D01", "删除上周的临时用电审批记录", 'delete')
T("D02", "把重复的工作票删掉", 'delete')
T("D03", "清空所有已完成的隐患排查任务", 'delete')
T("D04", "取消明天的倒闸操作任务", 'delete')
T("X01", "那个安全反馈我已经处理掉了", 'complete')
T("X02", "这个隐患分析搞完了", 'complete')
T("X03", "我这边'工作票'完事了", 'complete')
T("X04", "'安全统计月报'总算交上去了", 'complete')
T("X05", "OK了那个设备台账修好了", 'complete')
T("X06", "这个月事故分析做完了没有", 'query')
T("X07", "还没做完呢安规考试统计", 'query')
T("X08", "故障分析报告我不做了取消掉", 'delete')
T("X09", "变电站的倒闸操作票我做好了", 'complete')
T("X10", "线路巡视的日志我写完了", 'complete')
T("Z01", "你好，今天有什么安全任务吗", 'chat')
T("Z02", "谢谢提醒", 'chat')
T("Z03", "好的知道了", 'chat')
T("Z04", "哈哈有意思", 'chat')
T("Z05", "再见", 'chat')

log("=" * 70)
log("  国家电力集团 · 安全检测部门 · 任务助理逻辑验证")
log("  时间: " + datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
log("  报告: " + REPORT_FILE)
log("=" * 70)
log("")

passed = 0
failed = 0
failures = []

for label, text, exp_intent, notes in TESTS:
    intent, data = route_intent(text, USER)
    kw = data.get('keyword', '') if intent == 'complete' else ''
    uname = data.get('user_name', '') if intent == 'complete' else ''
    ok = (intent == exp_intent)
    status = 'OK' if ok else 'FAIL'
    log('[' + status + '] ' + label + ' [' + notes + ']')
    log('  输入: ' + text)
    extra = (' | kw=' + kw[:40]) if kw else ''
    extra += (' | who=' + uname) if uname else ''
    log('  意图: ' + intent + ' (期望: ' + exp_intent + ')' + extra)
    if not ok:
        log('  *** 失败! 期望=' + exp_intent + ' 实际=' + intent)
        failures.append((label, text, exp_intent, intent, notes))
        failed += 1
    else:
        passed += 1
    log("")

log("=" * 70)
log("  总计: " + str(passed+failed) + " | OK " + str(passed) + " | FAIL " + str(failed))
if failures:
    log("  失败详情:")
    for lbl, txt, exp, act, note in failures:
        log("    " + lbl + ": '" + txt + "' -> 期望=" + exp + ", 实际=" + act + " [" + note + "]")
else:
    log("  *** 全部通过！***")
log("=" * 70)

with open(REPORT_FILE, 'w', encoding='utf-8') as f:
    f.write('\n'.join(log_lines))
print("\n报告: " + REPORT_FILE)
