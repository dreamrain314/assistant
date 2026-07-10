from flask import Flask, request, jsonify, render_template
import json
import re
import socket
import requests as http_requests
from datetime import datetime, timedelta
from openai import OpenAI
from dotenv import load_dotenv

# 加载 .env 环境变量（Supabase URL/Key 等）
load_dotenv()

from db_utils import db
import uuid

app = Flask(__name__)

# ================= 待确认操作暂存（内存中，重启丢失） =================
# 用于删除前的二次确认：key=op_id, value={'type':'delete','sql':'...','preview':'...','condition':'...'}
# 未来可换 Redis 以支持多进程持久化
pending_ops = {}

# ================= 配置 DeepSeek =================
DEEPSEEK_API_KEY = "REMOVED_DEEPSEEK_KEY"
client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com/v1")


# ====================================================================
# 闲聊处理（快速匹配 + AI 兜底）
# ====================================================================

def chat_directly(user_input, user_name):
    """
    处理闲聊/问候类问题。优先快速匹配，失败则调 AI。
    """
    ui = user_input.strip().lower()

    # 快速匹配
    if ui in ('你好', 'hi', 'hello', '嗨', '在吗', '在不在'):
        return f"你好 {user_name}！有什么需要我帮忙的吗？"
    if '你是谁' in ui or '你叫什么' in ui:
        return "我是你的任务助理小助手，专门帮你管理任务、提醒截止时间、跟踪进度。有什么需要帮忙的吗？"
    if '你能做什么' in ui or '你有什么功能' in ui or '你会什么' in ui:
        return f"{user_name}，我可以帮你：\n1. 录入任务（如\"张三明天交报告\"）\n2. 查询任务（如\"今天有哪些任务\"）\n3. 修改任务（如\"把报告截止时间改到后天\"）\n4. 删除任务\n5. 提醒截止时间\n\n也可以和我闲聊，试试说\"你好\"～"
    if '我是谁' in ui or '我叫什么' in ui or '我的名字' in ui:
        return f"你是 {user_name}，当前登录的用户。"
    if '谢谢' in ui or '感谢' in ui:
        return f"不客气 {user_name}！随时找我。"
    if ui in ('再见', '拜拜', 'bye', '晚安'):
        return f"再见 {user_name}，有需要随时找我！"

    # AI 兜底
    reply = ai_reply(
        f"你是一个友好的任务助理，当前用户是{user_name}。简洁自然回复，禁止Markdown。",
        f"用户说：{user_input}\n请简短友好地回复（1-3句话），可以顺便引导用户使用你的任务管理功能。",
        temperature=0.7, max_tokens=200
    )
    return reply or f"你好 {user_name}，有什么需要帮忙的吗？"


# ====================================================================
# 统一意图路由（覆盖 chat/query/add/update/delete/confirm/cancel）
# ====================================================================

def route_intent(user_input, user_name):
    """
    先快速判断是否闲聊，否则交给 classify_and_extract。
    返回 (intent_str, extracted_data_dict)
    """
    ui = user_input.strip()
    import re as _re

    # ====== 第一优先级："完成"意图（排除"计划"表述） ======
    plan_patterns = [
        '要.*做完', '要.*完成', '需要.*完成', '得.*做完', '必须.*完',
        '计划.*完', '打算.*完', '准备.*完', '应该.*完', '要求.*完',
        '希望.*完', '想.*做完', '争取.*完', '预计.*完', '安排.*做',
        '布置.*任务', '有一个.*任务', '有一个.*工作', '有.*要做',
    ]
    is_plan = any(_re.search(p, ui) for p in plan_patterns)
    if not is_plan:
        complete_keywords = [
            '完成了', '做好了', '搞定了', '写完了', '做完了', '已经.*了',
            '提交了', '结束了', '办完了', '办妥了', '弄完了', '干完了',
            '交完了', '完成了的', '已做完', '已写好', '已提交', '已搞定',
            '全部.*完', '都.*完了', '就.*完了', '终于.*完了',
            '处理掉了', '处理完了', '修好了', '修完了',
            '完事了', '完事儿', '交上去了', '交上了', '交掉了',
            '做掉了', '弄好了', '清掉了', '搞完了', '搞掉了',
            '改好了', '改完了', '帮.*交了', '替.*完了', '帮.*完了',
        ]
        task_words = [
            # 通用任务词
            '任务', '试卷', '报告', '作业', '项目', '工作', '事情', '我的',
            '题目', '文档', '方案', '计划书', '报表', '总结', '汇报',
            '设计', '开发', '测试', '审查', '检查', '整理', '编写',
            '日报', '周报', '月报', '论文', '代码', 'PPT', '演示', '合同',
            '申请', '审批', '会议', '纪要', '邮件', '通知', '公告',
            '翻译', '调研', '分析', '评估', '预算', '报销', '采购',
            '培训', '考核', '绩效', '预案', '脚本', '画图', '海报',
            '视频', '原型', '计划', '需求', '调研', '复盘', '总结',
            '事儿', '活', '活儿', 'bug', 'Bug', 'BUG',
            # 电力安全检测行业专用词
            '安全', '检测', '巡检', '隐患', '排查', '事故', '故障', '风险',
            '整改', '验收', '监测', '维保', '维修', '保养', '台账',
            '调度', '值班', '交接班', '日志', '运行', '设备', '线路',
            '变电站', '配电', '输电', '发电', '供电', '停电', '送电',
            '倒闸', '带电', '接地', '绝缘', '耐压', '继保', '计量',
            '应急预案', '演练', '反事故', '安全培训', '安规', '两票',
            '工作票', '操作票', '动火', '高空', '有限空间', '临时用电',
            '反馈', '统计', '数据', '指标', '对标', '考核表', '评分',
            '季报', '年报', '快报', '简报', '通报', '函', '请示',
        ]
        # ★ 疑问式排除："做完了没有"/"写完了吗" 等 → 直接返回 query
        if _re.search(r'(?:完了|好了|定了|交了|掉了|完成了)\s*(?:没有|了吗|吗|没呢|没啊|没|不)\s*$', ui):
            return 'query', {'question': ui}
        is_complete = any(_re.search(kw, ui) for kw in complete_keywords) and (
            any(tw in ui for tw in task_words)
            # ★ 引号兜底：有引号 + 完成动词 → 一定是完成任务（即使关键词不在词表中）
            or bool(_extract_quoted(ui))
        )
        if is_complete:
            # ★ 提取完成人（引号前的人名或"我"→当前用户）
            completer = _extract_completer_name(ui, user_name)
            # ★ 引号精确匹配：用户用 '任务名' 或 "任务名" 指定了确切任务
            quoted = _extract_quoted(ui)
            if quoted:
                return 'complete', {'keyword': quoted, 'user_name': completer}
            # 正则提取任务关键词（省去AI调用，快1-2秒）
            kw = ui
            # 去掉完成相关的词和所有格代词（"我的"必须在"我"之前，否则"我"先被删会导致"的"裸奔）
            for remove in ['已经','了','完成','做好','搞定','写完','做完','提交','结束','办完','我的','你的','他的','她的','这个','那个','把']:
                kw = kw.replace(remove, '')
            # 替换独立"我"/"你"为当前用户名（不直接删除，保留任务归属信息）
            kw = kw.replace('我', completer)
            kw = kw.replace('你', completer)
            # 去掉开头的虚词/助词（"的"/"了"/"吗"/"呢"等不能作为任务名的开头）
            kw = re.sub(r'^[的了吗呢啊着过吧嗯哦哈呀]+', '', kw)
            kw = kw.strip()[:30]
            return 'complete', {'keyword': kw or ui[:30], 'user_name': completer}

    # ====== 第二优先级：闲聊检测 ======
    chat_patterns = [
        '你好', 'hi', 'hello', '嗨', '在吗', '在不在', '哈喽',
        '你是谁', '你叫什么', '你能做什么', '你有什么功能', '你会什么', '你能干啥',
        '我是谁', '我叫什么', '我的名字', '我叫啥',
        '谢谢', '感谢', '多谢', '3q', 'thx', '辛苦', '麻烦了',
        '再见', '拜拜', 'bye', '晚安', '明天见', '回见', '88',
        '哈哈', '嘿嘿', '嗯嗯', '知道了', '好的', 'ok', '嗯', '哦',
        '今天天气', '讲个笑话', '聊聊天', '无聊', '放松', '休息',
        '吃饭', '睡觉', '累了', '困了', '好累', '好困',
    ]
    for p in chat_patterns:
        if p in ui:
            return 'chat', {}

    # ====== 第三优先级：正则快速预判（省AI调用，更可靠） ======
    # 更新检测
    if _re.search(r'(改到|推迟|提前|延期|推到|推后|往后推|改成|标记为|改成.*完成)', ui):
        return 'update', {'search_condition': ui, 'new_status': '', 'new_deadline': ''}
    # 删除检测
    if any(kw in ui for kw in ('删掉', '删除', '清空', '清除', '去掉', '移除', '取消')):
        return 'delete', {'delete_condition': ui}
    # 疑问检测
    if any(kw in ui for kw in ('吗', '呢', '什么', '哪些', '怎么', '如何', '谁', '几个', '多少')):
        return 'query', {'question': ui}

    # ====== 第四优先级：AI 精细分类 ======
    result = classify_and_extract(ui)
    intent = result.get('intent', 'add')

    if intent == 'add' and any(kw in ui for kw in ('吗', '呢', '什么', '哪些', '怎么', '如何', '谁')):
        intent = 'query'
        result['question'] = ui

    return intent, result


# ====================================================================
# 通用规则（注入所有 AI 调用）
# ====================================================================
OUTPUT_FORMAT_RULE = """
输出格式要求（非常重要）：
- 禁止使用任何 Markdown 格式符号：不要用 **加粗**、*斜体*、# 标题、- 无序列表
- 如果需要列出多个项目（如任务列表），每项必须独占一行，项与项之间必须换行
- 换行直接用回车即可，禁止把所有内容连成一段
- 需要列举时用 "1." "2." 或 "·" 开头
- 保持简洁清晰的纯文本风格
"""


# ====================================================================
# 三层防护：任务查找 + 更新验证
# ====================================================================

def _find_matching_task(user_name, action_keyword, team_name='默认小组'):
    """精确+模糊匹配（限定本组）。"""
    team = db.get_team(team_name)
    tid = team['id'] if team else None
    try:
        base = db.supabase.table('records').select('*')
        if tid: base = base.eq('team_id', tid)
        r = base.eq('name', user_name).like('action', f'%{action_keyword}%').order('created_at', desc=True).limit(1).execute()
        if r.data: return r.data[0], 'exact'
        r = base.neq('status', '已完成').like('action', f'%{action_keyword}%').order('created_at', desc=True).limit(3).execute()
        if r.data: return r.data[0], 'fuzzy'
        for word in action_keyword.split():
            if len(word) >= 2:
                r = base.neq('status', '已完成').like('action', f'%{word}%').order('created_at', desc=True).limit(1).execute()
                if r.data: return r.data[0], 'keyword_split'
        # 字符级：取前/后2-3字搜（如"写完试卷"→"%写完%"匹配"写完我的试卷"）
        for n in [3, 2]:
            sub = action_keyword[:n]
            if len(sub) >= 2:
                r = base.neq('status', '已完成').like('action', f'%{sub}%').order('created_at', desc=True).limit(3).execute()
                if r.data: return r.data[0], 'char_match'
                tail = action_keyword[-n:]
                if tail != sub and len(tail) >= 2:
                    r = base.neq('status', '已完成').like('action', f'%{tail}%').order('created_at', desc=True).limit(3).execute()
                    if r.data: return r.data[0], 'char_tail'
    except Exception as e:
        print(f"[DB] _find_matching_task 失败: {e}")
    return None, None


def handle_complete(keyword, user_name, team_name='默认小组'):
    team = db.get_team(team_name)
    tid = team['id'] if team else None
    matches = []
    try:
        base = db.supabase.table('records').select('*').eq('name', user_name).neq('status', '已完成')
        if tid: base = base.eq('team_id', tid)
        for st in [keyword, keyword[:4], keyword[:3], keyword[:2]]:
            if len(st) >= 2:
                r = base.like('action', f'%{st}%').order('created_at', desc=True).limit(5).execute()
                matches = r.data or []
                if matches: break
        # ★ 跨用户搜索：自己名下找不到 → 扩展到全组成员（不过滤状态）
        if not matches:
            base_all = db.supabase.table('records').select('*')
            if tid: base_all = base_all.eq('team_id', tid)
            for st in [keyword, keyword[:4], keyword[:3], keyword[:2]]:
                if len(st) >= 2:
                    r = base_all.like('action', f'%{st}%').order('created_at', desc=True).limit(5).execute()
                    matches = r.data or []
                    if matches: break
    except Exception as e:
        print(f"[DB] handle_complete failed: {e}")
    if not matches:
        return {'result': f'没找到你正在做的「{keyword}」，要新建一条已完成记录吗？', 'intent': 'complete'}, True
    if len(matches) == 1:
        t = matches[0]
        db.supabase.table('records').update({'status': '已完成'}).eq('id', t['id']).execute()
        act = str(t.get('action', ''))
        reply = ai_reply("你是友好的任务助理。用纯文本。",
            f"已将「{act}」标记为已完成。一句话确认。{OUTPUT_FORMAT_RULE}")
        return {'intent': 'complete', 'result': reply or f'已将「{act}」标记为完成！'}, True
    # ★ 多匹配时显示负责人+任务名，防止同名任务分不清
    lines = []
    for i, t in enumerate(matches[:5], 1):
        who = str(t.get('name', '?'))
        what = str(t.get('action', '?'))
        dl = str(t.get('deadline', '无'))
        lines.append(f"{i}. {who}：{what}（截止：{dl}）")
    nl = chr(10)
    msg = f"找到 {len(matches)} 个匹配任务，回复序号选择要完成哪一个：" + nl + nl.join(lines)
    return {'intent': 'complete', 'result': msg}, True

def _find_similar_task(user_name, action_keyword, team_name='默认小组'):
    """查重：限定本组内搜索相似未完成任务。"""
    team = db.get_team(team_name)
    tid = team['id'] if team else None
    try:
        kw = action_keyword[:20]
        base = db.supabase.table('records').select('*').eq('name', user_name).neq('status', '已完成')
        if tid: base = base.eq('team_id', tid)
        r = base.like('action', f'%{kw}%').order('created_at', desc=True).limit(3).execute()
        if r.data: return r.data[0]
        for n in [10, 6, 4, 2]:
            sub = kw[:n]
            if len(sub) < 2: continue
            r = base.like('action', f'%{sub}%').order('created_at', desc=True).limit(3).execute()
            if r.data: return r.data[0]
        for word in kw.split():
            if len(word) >= 2:
                r = base.like('action', f'%{word}%').order('created_at', desc=True).limit(3).execute()
                if r.data: return r.data[0]
        for n in [3, 2]:
            sub = kw[:n]
            if len(sub) >= 2:
                r = base.like('action', f'%{sub}%').order('created_at', desc=True).limit(3).execute()
                if r.data: return r.data[0]
                tail = kw[-n:]
                if tail != sub and len(tail) >= 2:
                    r = base.like('action', f'%{tail}%').order('created_at', desc=True).limit(3).execute()
                    if r.data: return r.data[0]
    except Exception as e:
        print(f"[DB] _find_similar_task 失败: {e}")
    return None


def _verify_update(task_id, field, expected_value):
    """更新后查询验证（Supabase）。返回 (success, actual_value)。"""
    try:
        result = db.supabase.table('records').select(field).eq('id', int(task_id)).execute()
        if result.data:
            actual = str(result.data[0].get(field, '') or '')
            return actual == str(expected_value), actual
    except Exception as e:
        print(f"[DB] _verify_update 失败: {e}")
    return False, None

# ====================================================================
# 辅助函数：校验并规范化 deadline 字符串
# ====================================================================

def validate_deadline(deadline_str):
    if not deadline_str or str(deadline_str).strip() in ('', 'null', 'None', '无'):
        return None
    deadline_str = str(deadline_str).strip()
    formats = [
        '%Y-%m-%d %H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d',
        '%Y/%m/%d %H:%M', '%Y/%m/%d', '%Y年%m月%d日 %H:%M',
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(deadline_str, fmt)
            return dt.strftime('%Y-%m-%d %H:%M')
        except ValueError:
            continue
    print(f"[WARN] deadline 格式无法解析，已置空: {deadline_str}")
    return None


# ====================================================================
# 代词清洗：action 中不能出现"我"/"你"/"他"等代词
# ====================================================================

def _clean_action_pronouns(action_text, task_name):
    """
    Replace personal pronouns in task action text with actual names or remove them.
    - "我"/"我的" → removed or replaced with task_name
    - "你"/"你的" → removed or replaced with task_name
    - "他"/"他的"/"她"/"她的" → removed or "其"
    """
    text = str(action_text or '')

    # Remove possessive pronouns first
    text = re.sub(r'我的', '', text)
    text = re.sub(r'你的', '', text)
    text = re.sub(r'他的', '', text)
    text = re.sub(r'她的', '', text)
    text = re.sub(r'其的', '', text)

    # Replace subject pronouns with task owner's name
    text = text.replace('我', task_name)
    text = text.replace('你', task_name)

    # "他"/"她" → "其" (gender-neutral when context unknown)
    text = text.replace('他', '其')
    text = text.replace('她', '其')

    # Clean up: double spaces, trim, deduplicate consecutive task names
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'(' + re.escape(task_name) + r')\s*\1', r'\1', text)

    return text


# ====================================================================
# 多人检测：A和B/A、B/A与B 模式
# ====================================================================

def _extract_multi_names(text, current_user=''):
    """
    Detect multi-person patterns like 'A和B', 'A、B', 'A与B', 'A跟B'.
    Resolves '我'/'自己' to current_user.
    Returns list of names (length > 1) or None if no multi-person pattern found.
    """
    connectors = r'(?:和|与|跟|同|、|,|，)'
    m = re.search(r'(\S{1,5})' + connectors + r'\s*(\S{1,5})', text)
    if not m:
        return None

    names = []
    for g in m.groups():
        g = g.strip()
        if g in ('我', '自己', ''):
            names.append(current_user or '未知')
        else:
            g = re.sub(r'[的要了]$', '', g)
            if g:
                names.append(g)

    # Check for a third person after the second match
    rest = text[m.end():]
    more = re.search(r'^\s*' + connectors + r'\s*(\S{1,5})', rest)
    if more:
        n = more.group(1).strip()
        if n in ('我', '自己', ''):
            names.append(current_user or '未知')
        else:
            n = re.sub(r'[的要了]$', '', n)
            if n:
                names.append(n)

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for n in names:
        if n not in seen:
            seen.add(n)
            unique.append(n)

    return unique if len(unique) > 1 else None


def _extract_quoted(text):
    """
    提取引号包裹的文本作为精确任务名。
    支持: '单引号'  "双引号"  「中文引号」 『中文双引号』
    返回第一个匹配的引号内容，无匹配返回 None。
    """
    for pat in [r'"([^"]+)"', r"'([^']+)'", r'「([^」]+)」', r'『([^』]+)』']:
        m = re.search(pat, text)
        if m:
            return m.group(1).strip()
    return None


def _extract_completer_name(text, current_user):
    """
    从"XX完成了/做完了/搞定了..."中提取完成人。
    - "我完成了..." → current_user
    - "张三完成了..." → 张三
    - 无明确人名 → current_user（宁可回退也不乱猜）
    """
    # 找到完成动词的位置
    m = re.search(r'(完成了|做好了|搞定了|写完了|做完了|提交了|结束了|办完了|弄完了|干完了|交完了|弄好了|写好了|办好了|做好了|干好了|处理掉了|处理完了|修好了|修完了|完事了|交上去了|清掉了|搞完了)'
                  r'|(完成|做好|搞定|写完|做完|提交|结束|办完|弄完|干完|交完|弄好|写好|办好|做好|干好|处理掉|修好|完事|交上|清掉|搞完)\\b',
                  text)
    if not m:
        return current_user

    before = text[:m.start()].strip()

    # 剥离末尾的时间副词/语气词
    adverbs = ['已经', '早就', '刚刚', '才', '终于', '今天', '昨天', '明天', '后天',
               '上午', '下午', '晚上', '都', '就', '也', '全', '全部', '基本上']
    changed = True
    while changed:
        changed = False
        for adv in adverbs:
            if before.endswith(adv):
                before = before[:-len(adv)].strip()
                changed = True

    # 无前置内容 → 默认当前用户
    if not before:
        return current_user

    # 前置内容超过 8 个字 → 大概率是任务描述而非人名，谨慎处理
    name_m = re.search(r'(\S{1,4})$', before)
    if not name_m:
        return current_user

    name = name_m.group(1)

    # ---- 排除明显不是人名的候选 ----

    # "我"结尾 → 当前用户（处理"操作票我"→"我"的情况）
    if name.endswith('我'):
        return current_user

    # 黑名单：虚词、介词、标点残留
    if name in ('我', '自己', '', '把', '将', '的', '了', '被', '让', '给', '和', '与'):
        return current_user

    # 单字且前面内容长 → 极大概率是任务描述尾字，不是人名
    if len(name) == 1 and len(before) > 5:
        return current_user

    # 候选名是/包含任务关键词 → 是任务内容不是人名（先于量词检查）
    task_like = ['报告', '记录', '数据', '台账', '工作票', '操作票', '通知', '方案',
                 '总结', '报表', '统计', '分析', '日志', '测试', '检查', '检测',
                 '巡检', '演练', '培训', '审批', '验收', '整改', '维修', '维保',
                 '工作', '任务', '试卷', '作业', '项目', '文档', '合同', '预案',
                 '简报', '快报', '季报', '年报', '月报', '周报', '日报', '论文',
                 '指标', '评分', '考核', '反馈', '隐患', '事故', '故障', '调度',
                 '票', '单', '表', '书', '稿', '图', '件', '录', '据']
    if name in task_like or any(tw in name for tw in task_like):
        return current_user

    # 候选名以量词开头且首字非姓氏 → 是任务描述不是人名
    # （"份工作票"→量词 + 名词；但"张"既是量词也是姓氏，不能一刀切）
    common_surnames = set('王李张刘陈杨黄赵周吴徐孙马胡朱郭何罗高林郑梁谢唐许冯宋韩邓彭曹曾田董潘袁蔡蒋余于杜叶程魏苏吕丁任卢姚钟姜崔谭陆范汪廖石金贾韦夏傅方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴莫孔向汤')
    if name[0] not in common_surnames:
        measure_words = set('份个条项次台套批件颗块段本支只双对群些点种类样位名间座辆艘架篇幅首篇封则门堂场遍趟回下顿阵')
        if name[0] in measure_words:
            return current_user

    # 前置内容太长（>8字）且候选名不在常见姓氏中 → 安全回退
    if len(before) > 8 and len(name) >= 1 and name[0] not in common_surnames:
        return current_user

    # 清理尾部的"的"/"了"
    name = re.sub(r'[的了]$', '', name)
    return name if name else current_user


# ====================================================================
# 核心函数：AI 意图分类 + 数据提取（支持 add/query/delete/update）
# ====================================================================

def classify_and_extract(user_input, context=''):
    """
    用 AI 一次性完成意图判断 + 数据提取。
    支持四种意图：add（录入）、query（查询）、delete（删除）、update（更新状态）

    参数:
        user_input (str): 用户当前输入
        context (str): 上一轮 AI 的回复内容，用于理解"这个"、"那个"等指代
    """
    now = datetime.now()
    current_date_str = now.strftime("%Y年%m月%d日")
    current_datetime_str = now.strftime("%Y-%m-%d %H:%M")
    current_weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()]

    # 构建上下文段落（如果有上一轮对话）
    context_section = ""
    if context and context.strip():
        context_section = f"""
对话上下文（我刚才回复用户的内容）：
{context.strip()}

"""

    prompt = f"""当前日期时间：{current_datetime_str}（{current_weekday}）
{context_section}
用户说："{user_input}"

请判断意图并提取数据。支持四种意图。

⚠️ 上下文理解（非常重要）：
- 如果提供了"对话上下文"，用户说的"这个"、"那个"、"它"等指代词，请从上下文中找到对应内容
- 例如上下文提到"试卷解析 — 龙四"，用户说"把这个任务删除" → 意图=delete，条件="龙四的试卷解析任务"
- 例如上下文列出多个任务，用户说"删掉第一个" → 根据上下文中的第一条任务来确定条件
- 用户可能用简称或不完整描述，请结合上下文补全

## 1. intent = "add"（录入任务）
用户在描述/记录/汇报一个任务。
  典型表述：
  - "张三完成了大屏项目"、"李四有一个提交报告的任务，明天截止"
  - "这个任务截至今天"、"报告今天必须完成"（告知deadline，不是查询）
  口诀：有人名+具体事+时间词 → add；有疑问词（哪些/几个/什么）+时间词 → query
  "我"字判断："我"+疑问词(哪些/什么/有没有/还有什么)=query；"我"+动作描述(完成了/做了/在做)=add
	  ⚠️ "那/这个XX搞定了"→update：如果用户说"那个写代码的任务搞定了"、"这个报告做好了"等，已经用"那个/这个"指代已有任务+完成动词，意图应为 update 而非 add！

  提取字段：name（人名）、action（任务描述）、status（默认"未完成"，明确说"完成了"则"已完成"）、deadline

  ⚠️ deadline 提取（非常重要，最容易出错）：
  以下情况 deadline 必须设为今天日期（{current_date_str}）：
    - "今天要交"、"今天要做完"、"今天要做"、"今天有.*要做"、"今天要完成"
    - "今天交"、"今天提交"、"今天到期"、"今天截止"、"今天搞定"、"今天处理"
    - "今晚"、"今晚X点"、"今天内"、"今天之前"、"今日"、"今儿"
    - 句中同时有"今天"和"交/提交/要交/完成/做完/截止/到期/搞定/处理/弄/做" → deadline=今天
  以下为相对日期 → 绝对时间转换表：
    - "今晚X点" → 今天 X:00；"今晚"=今天23:59
    - "明天X点" → {current_date_str}+1天；"明天"=明天23:59；"明日"=明天23:59
    - "后天X点" → {current_date_str}+2天；"后天"=后天23:59；"后日"=后天23:59
    - "大后天"/"三天后" → {current_date_str}+3天
    - "这周六"/"本周六" → 本周六 18:00；"这周日"/"本周日" → 本周日 18:00
    - "下周X" → 下周对应星期X（"下周一"=下周一09:00，"下周五"=下周五18:00）
  注意区分描述性时间和截止时间：
    - "7月份工作开题报告"中"7月份"是报告主题，不是deadline
    - "今天要交"中"今天"才是deadline
    - 一句话中同时有描述性时间(如"7月份")+紧迫词(如"今天要交") → deadline取紧迫词对应时间
  没有提到任何截止时间 → deadline留空 ""

## 2. intent = "query"（查询问题）
用户在提问、询问信息。
  典型表述：
  - "今天有哪些任务"、"张三有几个未完成的任务"
  - "XX任务在哪一天"、"XX任务的截止时间是什么"
  - "显示所有任务"、"谁有任务"
  - "我还有什么任务、我还没做完的工作有哪些、我的任务、
  - 这周有什么任务"、"明天有哪些"

  提取字段：question（把"我"替换成用户名，重述为清晰查询语句。"我还有什么任务"→query，"我完成了XX"→add）

## 3. intent = "delete"（删除/清空任务）★新增
用户要删除、清空、移除任务。
  典型表述：
  - "清空今天的所有任务"、"删除今天的任务"
  - "把张三的XX任务删掉"、"移除所有已完成的任务"
  - "删掉李四的所有任务"

  提取字段：delete_condition（重述删除条件，如"今天的所有任务"→"截止日期为今天的所有任务"）

## 4. intent = "update"（更新任务状态或截止时间）
用户要修改已有任务的状态 或 截止时间。
  典型表述（改状态）：
  - "把张三的提交报告标记为已完成"
  - "将李四的客户演示改成进行中"
  - "XX任务完成了"（如果像是说已有任务的状态变化 → update；如果是首次汇报 → add）
	  - "那个写代码的任务搞定了"、"这个报告做完了"→ update（用那个/这个指代已有任务）
  典型表述（改截止时间）：
  - "把张三的开题报告的截止时间改成后天"
  - "XX任务推迟到下周X"、"XX改到大后天交"
  - "XX的deadline改成明天下午"

  提取字段：
    - search_condition（描述要找到哪个任务）
    - new_status（新状态，不改则留空 ""）
    - new_deadline（新截止时间 YYYY-MM-DD HH:MM，不改则留空 ""；相对时间按add的deadline规则转换）
  可以同时改状态和截止时间，也可以只改其中一个

## 5. intent = "confirm"（确认操作）★新增
用户在确认之前系统反问的操作。需结合上下文判断。
  上下文通常是系统反问"确定要删除XXX吗？回复'确定'确认"
  典型表述：
  - "确定"、"确认"、"是的"、"对"、"没错"、"可以"、"行"、"好的删吧"
  - 结合上下文能判断用户在确认什么操作

  提取字段：无需额外字段（系统根据 pending_op_id 执行暂存的操作）

## 6. intent = "cancel"（取消操作）★新增
用户在取消之前系统反问的操作。需结合上下文判断。
  典型表述：
  - "取消"、"算了"、"不用了"、"不要了"、"先不删了"、"不删"

  提取字段：无需额外字段

{OUTPUT_FORMAT_RULE}

返回纯JSON（不要```标记）：
- add: {{"intent":"add","name":"","action":"","status":"","deadline":""}}
- query: {{"intent":"query","question":""}}
- delete: {{"intent":"delete","delete_condition":""}}
- update: {{"intent":"update","search_condition":"","new_status":"","new_deadline":""}}
- confirm: {{"intent":"confirm"}}
- cancel: {{"intent":"cancel"}}
"""
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0, max_tokens=250
        )
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(content)

        intent = parsed.get('intent', 'add')
        if intent not in ('add', 'query', 'delete', 'update', 'confirm', 'cancel'):
            intent = 'add'

        if intent == 'add':
            if 'deadline' in parsed:
                parsed['deadline'] = validate_deadline(parsed['deadline'])
            else:
                parsed['deadline'] = None
            # 兜底规则：AI 未提取 deadline 时，用正则检测常见日期表述强制补上
            if not parsed['deadline']:
                time_words = r'(交|完成|做完|截止|到期|提交|要做|要做完|要完成|弄完|搞定|结束|处理|办完|上交|交付|搞定它|解决)'
                if re.search(r'今天.*' + time_words, user_input) or re.search(r'今晚|今天内|今天之前|今日', user_input):
                    parsed['deadline'] = now.strftime('%Y-%m-%d') + ' 23:59'
                elif re.search(r'明天.*' + time_words, user_input) or re.search(r'明日', user_input):
                    from datetime import timedelta
                    d = now + timedelta(days=1)
                    parsed['deadline'] = d.strftime('%Y-%m-%d') + ' 23:59'
                elif re.search(r'后天.*' + time_words, user_input) or re.search(r'后日', user_input):
                    from datetime import timedelta
                    d = now + timedelta(days=2)
                    parsed['deadline'] = d.strftime('%Y-%m-%d') + ' 23:59'
                elif re.search(r'大后天|三天后', user_input):
                    from datetime import timedelta
                    d = now + timedelta(days=3)
                    parsed['deadline'] = d.strftime('%Y-%m-%d') + ' 23:59'
            parsed.setdefault('name', '未知')
            parsed.setdefault('action', user_input)
            parsed.setdefault('status', '未完成')
        elif intent == 'query':
            parsed.setdefault('question', user_input)
        elif intent == 'delete':
            parsed.setdefault('delete_condition', user_input)
        elif intent == 'update':
            parsed.setdefault('search_condition', user_input)
            parsed.setdefault('new_status', '')
            # 如果有 new_deadline，校验格式
            if parsed.get('new_deadline') and parsed['new_deadline'].strip():
                parsed['new_deadline'] = validate_deadline(parsed['new_deadline'])
            else:
                parsed['new_deadline'] = ''

        return parsed

    except Exception as e:
        print("AI 意图分类出错:", e)
        return {"intent": "add", "name": "未知", "action": user_input, "status": "未完成", "deadline": None}


# ====================================================================
# 辅助函数：生成自然语言回复（通用）
# ====================================================================

def ai_reply(system_instruction, user_prompt, temperature=0.5, max_tokens=1000):
    """
    通用 AI 回复生成器。封装了 DeepSeek 调用 + 异常降级。
    返回 AI 回复文本；失败时返回 None。
    """
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_prompt}
            ],
            temperature=temperature, max_tokens=max_tokens
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"AI 调用出错: {e}")
        return None


# ====================================================================
# 录入确认回复
# ====================================================================

def generate_add_reply(name, action, status, deadline):
    deadline_info = f"截止时间：{deadline}" if deadline else "没有截止时间"
    reply = ai_reply(
        "你是一个友好的任务助理。",
        f"""系统刚记录了一条任务：负责人={name}，内容={action}，状态={status}，{deadline_info}。
请用自然口语化中文确认。有截止时间就温馨提醒。一句话即可。
{OUTPUT_FORMAT_RULE}"""
    )
    if reply:
        return reply
    # 降级
    msg = f"已记录：{name} 的 {action}（{status}）"
    if deadline:
        msg += f"\n截止时间：{deadline}"
    return msg


# ====================================================================
# 查询结果 → 口语化回复
# ====================================================================

def convert_to_natural_language(question, result_msg, row_count, overdue_count=0):
    overdue_hint = ""
    if overdue_count > 0:
        overdue_hint = f"\n特别注意：结果中有 {overdue_count} 条已超时（标记为【已超时】），请在回复最前面用醒目方式提醒用户。"

    reply = ai_reply(
        "你是任务助理。直接复述下方分类结果。禁止Markdown。",
        f"""用户问题："{question}"
查询结果：
{result_msg}
共 {row_count} 条。
{overdue_hint}

转化规则：
1. 简洁自然，像日常对话
2. 记录数为0时鼓励一下；有【已超时】标记的任务放最前面用 ⚠️ 提醒
3. 自然提及 deadline，有多少条就列多少条，全部列出不要省略
4. 禁止 Markdown 格式符号
5. 不要出现"查询"、"数据库"、"记录"等术语

⚠️ 换行规则（最重要，违反视为错误）：
列出任务时必须每条一行用换行分隔，有多少条就列多少条，不要省略。格式：
你有N个任务：
张三：写周报（截止：今天22:00）
李四：代码审查（截止：明天15:00）
严禁把多条任务写在同一行，严禁说"还有X条未列出"之类省略语句
{OUTPUT_FORMAT_RULE}"""
    )
    return reply if reply else result_msg


# ====================================================================
# 模糊匹配：查询无结果时尝试找相似任务
# ====================================================================

def fuzzy_match(question, team_name='默认小组'):
    """
    当精确查询无结果时，从本组数据库中拉取最近任务。
    """
    team = db.get_team(team_name)
    tid = team['id'] if team else None
    data = []
    if tid:
        try:
            r = db.supabase.table('records').select('name,action,status,deadline') \
                .eq('team_id', tid).order('created_at', desc=True).limit(30).execute()
            data = r.data or []
        except Exception: pass
    if not data:
        return None
    rows = [tuple(d.get(c,'') for c in ['name','action','status','deadline']) for d in data]
    cols = ['name','action','status','deadline']

    # 格式化已有任务列表给 AI 参考
    tasks_list_parts = []
    for r in rows:
        d = dict(zip(cols, r))
        dl = d.get('deadline') or '无截止时间'
        tasks_list_parts.append(f"· {d['name']}：{d['action']}（{d['status']}，截止：{dl}）")
    tasks_list = "\n".join(tasks_list_parts)

    reply = ai_reply(
        "你是一个任务助理。用纯文本回复，禁止 Markdown。",
        f"""用户问："{question}"
数据库中没有精确匹配的结果。

数据库中现有任务：
{tasks_list}

请判断用户可能在找哪个任务（最多3个最相关的）：
- 如果找到了相似的：回复 "没有找到完全匹配的结果。您是指以下任务吗？" 然后逐行列出来
- 如果没有相关的：回复 "没有找到相关任务。"
- 每条格式："· 任务描述 — 负责人（截止：时间）"

{OUTPUT_FORMAT_RULE}"""
    )
    return reply


# ====================================================================
# 保留：旧版解析（兼容 /add）
# ====================================================================

def parse_with_ai(user_input):
    now = datetime.now()
    current_datetime_str = now.strftime("%Y-%m-%d %H:%M")
    current_weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()]
    parsed = classify_and_extract(user_input)
    # 兼容旧接口只返回 add 格式
    if parsed.get('intent') != 'add':
        return {"name": "未知", "action": user_input, "status": "无", "deadline": None}
    return parsed


# ====================================================================
# 预留：推送通知
# ====================================================================

def send_push(user_id, message):
    print(f"[PUSH 占位] 向用户 {user_id} 推送: {message}")
    pass


# ====================================================================
# 内部执行函数
# ====================================================================

def do_add(user_text, name, action, status, deadline, is_public=True, assigned_to='', team_name='默认小组', created_by=''):
    # 成员验证：检查负责人是否在本小组
    team = db.get_team(team_name)
    team_id = team['id'] if team else None
    if team_id and name and name != '未知':
        member = db.get_user_in_team(name, team_name) or db.get_user(name)
        if not member:
            return {'error': f'「{name}」不是本小组成员，请先到用户管理中添加该成员。'}
    # 获取创建者的 user_id
    creator_id = None
    if created_by:
        creator = db.get_user(created_by)
        if creator:
            # 通过 Supabase 查用户完整记录获取 id
            try:
                r = db.supabase.table('users').select('id').eq('name', created_by).execute()
                if r.data: creator_id = r.data[0].get('id')
            except Exception: pass
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    action = _clean_action_pronouns(action, name)   # 清洗代词
    db.insert('records', {
        'name': name, 'action': action, 'status': status,
        'note': user_text, 'created_at': now, 'deadline': deadline,
        'is_public': 1 if is_public else 0,
        'assigned_to': assigned_to, 'team_id': team_id,
        'user_id': creator_id
    })
    reply = generate_add_reply(name, action, status, deadline)
    deadline_str = f"，截止时间：{deadline}" if deadline else ""
    fallback = f"✅ 已为 {name} 安排任务：{action}，状态：{status}{deadline_str}"
    return {
        "intent": "add", "result": reply or fallback,
        "name": name, "action": action, "status": status,
        "deadline": deadline, "time": now,
        "is_public": is_public, "assigned_to": assigned_to,
        "message": fallback
    }


def do_query(question, current_user='', team_name='默认小组'):
    """
    查询流程：AI 生成 SQL → 注入 team_id → 执行 → 超时检测 → 口语化。
    current_user: 当前登录用户名
    team_name: 当前小组名，用于数据隔离
    """
    schema = db.get_schema()
    if not schema:
        return {'error': '数据库中没有表'}, 500

    # 强制校验小组存在（防止数据泄露到其他小组）
    team = db.get_team(team_name)
    if not team:
        return {'error': f'小组「{team_name}」不存在，请联系管理员创建小组后再查询'}, 400
    team_id = team['id']

    now = datetime.now()
    current_datetime_str = now.strftime('%Y-%m-%d %H:%M')

    # 构建身份提示（含 team_id 强制过滤）
    user_hint = ""
    if current_user:
        user_hint = f"""
当前登录用户：{current_user}
用户问"我"/"我的"时，指的就是 {current_user}。
用户问"我还有什么任务"/"我的任务"时，应查询 name='{current_user}' 的任务（包含公共任务 is_public=1）。
"""

    # 第一步：AI 生成 SQL
    prompt = f"""数据库为SQLite。结构：
{schema}

列说明：
- deadline: 截止时间 TEXT "YYYY-MM-DD HH:MM"，可为 NULL
- status: "未完成"/"已完成"/"进行中"
- created_at: 创建时间 TEXT
- name: 负责人
- action: 任务描述
- is_public: 1=公共任务(所有人可见), 0=指定人员任务
- assigned_to: 指定人员列表(逗号分隔)
- team_id: 小组ID，当前小组 team_id={team_id}
{user_hint}
当前时间：{current_datetime_str}

⚠️ 数据隔离规则（最高优先级，违反即为错误）：
所有查询必须包含 WHERE team_id={team_id}，这是强制要求！

查询规则：
1. "今天有哪些任务"/"今天要做什么" → 查所有未完成任务
2. "我还有什么任务"/"我的任务"/"我未完成的" → WHERE team_id={team_id} AND status!='已完成' AND (name='{current_user}' OR is_public=1 OR assigned_to LIKE '%{current_user}%')
3. "今天有哪些任务到期" → WHERE team_id={team_id} AND date(deadline) = date('now')
4. "明天有哪些" → WHERE team_id={team_id} AND date(deadline) = date('now', '+1 day')
5. "XX任务在哪一天/截止时间是什么" → SELECT action, deadline FROM records WHERE team_id={team_id} AND action LIKE '%XX%'
6. "这周有什么" → WHERE team_id={team_id} AND deadline >= date('now') AND deadline < date('now', '+7 days')
7. "所有未完成" → WHERE team_id={team_id} AND status != '已完成'
8. 找特定任务时优先用 LIKE '%关键词%' 而不是 =
9. 如果用户用了"我"但没有指明具体人名，就用 {current_user or '?'} 作为 name 条件

只返回SELECT语句，不要任何其他文字。

用户问题：{question}
"""
    sql_query = ai_reply(
        "你是一个SQL专家，只生成SELECT查询语句。",
        prompt, temperature=0, max_tokens=300
    )
    if not sql_query:
        return {'error': '调用AI生成SQL失败'}, 500

    sql_query = sql_query.strip()
    if not sql_query.upper().startswith('SELECT'):
        return {'error': '生成的查询不是SELECT语句，已拒绝执行'}, 400

    # 第二步：注入 team_id（兜底：AI 可能遗漏）
    if f'team_id={team_id}' not in sql_query and 'team_id =' not in sql_query:
        if 'WHERE' in sql_query.upper():
            # 在第一个 WHERE 后插入 team_id 条件
            sql_query = re.sub(r'(WHERE\s+)', rf'\1team_id={team_id} AND ', sql_query, count=1, flags=re.IGNORECASE)
        else:
            sql_query = sql_query.replace('FROM records', f'FROM records WHERE team_id={team_id}')

    # 第三步：执行
    try:
        rows, col_names = db.query(sql_query)
    except Exception as e:
        return {'error': f'执行SQL出错: {str(e)}'}, 500

    # 数据隔离：按 team_id 二次过滤（兜底保护，防止 _supabase_select 丢弃条件）
    if rows and 'team_id' in col_names:
        tidx = col_names.index('team_id')
        rows = [r for r in rows if r[tidx] == team_id]
    # 可见性过滤：只显示自己的 + 全体 + 分配到的
    # 但如果用户明确问了别人（如"小龙有什么任务"），显示那个人的
    target_user = current_user
    if current_user and question:
        # 检查问题中是否提到了其他已知用户名
        team = db.get_team(team_name)
        if team:
            members = db.get_team_members(team_name)
            for m in (members or []):
                mn = m.get('name','')
                if mn and mn != current_user and mn in question:
                    target_user = mn
                    break

    # 可见性过滤：非管理员查他人→只显示公开任务+全体
    restrict_to_public = (target_user != current_user) and not (db.get_user(current_user) or {}).get('is_admin', False)

    if target_user and rows:
        name_idx = next((i for i, c in enumerate(col_names) if c.lower() == 'name'), None)
        at_idx = next((i for i, c in enumerate(col_names) if c.lower() == 'assigned_to'), None)
        pub_idx = next((i for i, c in enumerate(col_names) if c.lower() == 'is_public'), None)
        if name_idx is not None:
            filtered = []
            for r in rows:
                task_name = str(r[name_idx] or '')
                is_public = r[pub_idx] in (1, True, '1') if pub_idx is not None else True
                # 非管理员查他人 → 只显示公开任务
                if restrict_to_public and not is_public:
                    continue
                if task_name == target_user:
                    filtered.append(r)
                elif task_name in ('', '全体', '所有人'):
                    filtered.append(r)
                elif at_idx is not None:
                    assigned = str(r[at_idx] or '')
                    if target_user in [x.strip() for x in assigned.split(',')]:
                        filtered.append(r)
            rows = filtered

    # 第三步：如果 0 结果 → 模糊匹配
    if not rows:
        fuzzy_result = fuzzy_match(question, team_name)
        if fuzzy_result:
            return {
                "intent": "query",
                "result": fuzzy_result,
                "raw_result": "没有精确匹配",
                "sql": sql_query,
                "count": 0,
                "overdue_count": 0
            }
        # 完全没有结果
        reply = ai_reply(
            "你是一个友好的任务助理。用纯文本，禁止 Markdown。",
            f"""用户问："{question}"。数据库中没有找到任何相关任务。
请用鼓励的语气告诉用户没有找到，可以建议换个关键词试试。
{OUTPUT_FORMAT_RULE}"""
        )
        return {
            "intent": "query", "result": reply or "没有找到相关任务。",
            "raw_result": "无", "sql": sql_query, "count": 0, "overdue_count": 0
        }

    # 第四步：超时检测 + 格式化
    overdue_count = 0
    deadline_idx = col_names.index('deadline') if 'deadline' in col_names else None
    status_idx = col_names.index('status') if 'status' in col_names else None

    marked_rows = []
    for row in rows:
        is_overdue = False
        if deadline_idx is not None:
            row_deadline = row[deadline_idx]
            row_status = row[status_idx] if status_idx is not None else ''
            if row_deadline and str(row_deadline).strip():
                if str(row_status).strip() not in ('已完成', '完成'):
                    dl_str = str(row_deadline).strip()
                    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
                        try:
                            dl = datetime.strptime(dl_str, fmt)
                            if dl < now:
                                is_overdue = True
                                overdue_count += 1
                            break
                        except ValueError:
                            continue
        marked_rows.append((row, is_overdue))

    if len(rows) == 1 and len(col_names) == 1:
        result_msg = f"查询结果：{rows[0][0]}"
    else:
        name_idx = col_names.index('name') if 'name' in col_names else 0
        action_idx = col_names.index('action') if 'action' in col_names else 1
        dl_idx = col_names.index('deadline') if 'deadline' in col_names else None
        pub_idx = col_names.index('is_public') if 'is_public' in col_names else None
        # 排序：超时优先，再按deadline升序
        def sort_key(item):
            row, is_overdue = item
            dl_str = str(row[dl_idx] or '9999') if dl_idx is not None else '9999'
            return (0 if is_overdue else 1, dl_str)
        marked_rows.sort(key=sort_key)
        # 判断是否全是已完成任务
        status_idx = col_names.index('status') if 'status' in col_names else None
        all_done = all(str(r[status_idx]) in ('已完成','完成') for r, _ in marked_rows) if status_idx is not None and marked_rows else False

        parts = []
        for row, is_overdue in marked_rows:
            name_val = str(row[name_idx] or '') or ('全体' if (pub_idx is not None and row[pub_idx] in (1, True, '1')) else '?')
            action_val = str(row[action_idx] or '?')
            dl_val = str(row[dl_idx] or '无截止') if dl_idx is not None else '无截止'
            n = len(parts) + 1
            if all_done:
                line = f"{n}. {name_val}：{action_val}（截止：{dl_val}）已完成"
            else:
                line = f"{n}. {name_val}：{action_val}（截止：{dl_val}）"
                if is_overdue: line = line + " 【已超时】"
            parts.append(line)
        result_msg = chr(10).join(parts) if parts else "没有找到符合条件的数据。"

    # 直接返回格式化结果（跳过AI重写，保证分类格式不变）
    label = "你" if target_user == current_user else target_user
    if all_done:
        header = f"{label}已经完成了 {len(rows)} 个任务：\n"
    else:
        header = f"{label}总共有 {len(rows)} 个任务：\n"
        if overdue_count > 0:
            header += f"⚠️ 有 {overdue_count} 条任务已超时！\n"
    header += "\n"
    return {
        "intent": "query", "result": header + result_msg,
        "raw_result": result_msg, "sql": sql_query,
        "count": len(rows), "overdue_count": overdue_count
    }


# ====================================================================
# 路由
# ====================================================================

@app.route('/')
def index():
    return render_template('index.html')


def do_delete(delete_condition, team_name='默认小组'):
    """删除流程：本组内搜索 → 优先最佳匹配 → 支持序号选择。"""
    if not delete_condition:
        return {'error': '缺少删除条件'}, 400
    keyword = delete_condition.strip()
    # 清理常见冗余词
    for filler in ['的这个任务','那个任务','这个任务','那个任务','这个','那个','的任务','一下','帮我','请','把','删掉','删除','删除掉','去掉','移除','取消']:
        keyword = keyword.replace(filler, '')
    keyword = keyword.strip()
    team = db.get_team(team_name)
    tid = team['id'] if team else None
    all_tasks = []
    for st in [keyword, keyword[:6], keyword[:4], keyword[:3], keyword[:2]]:
        if len(st) < 2: continue
        try:
            q = db.supabase.table('records').select('*').like('action', f'%{st}%').order('created_at', desc=True).limit(10)
            if tid: q = q.eq('team_id', tid)
            r = q.execute()
            if r.data: all_tasks = r.data; break
        except Exception: pass
    if not all_tasks:
        return {'intent': 'delete', 'result': '没有找到相关任务。', 'deleted_count': 0}
    if len(all_tasks) == 1:
        t = all_tasks[0]
        pv = '· %s：%s（状态：%s）' % (t.get('name','?'), t.get('action','?'), t.get('status','?'))
        op_id = str(uuid.uuid4())[:8]
        pending_ops[op_id] = {'type': 'delete', 'task_id': t.get('id'), 'preview': pv, 'count': 1}
        fb = '确定要删除以下任务吗？\n' + pv + '\n回复「确定」确认删除。'
        return {'intent': 'delete', 'result': fb, 'deleted_count': 0, 'pending_op_id': op_id, 'needs_confirmation': True}
    lines = []
    for i, t in enumerate(all_tasks[:10], 1):
        lines.append(str(i) + '. ' + str(t.get('name','?')) + '：' + str(t.get('action','?')) + '（' + str(t.get('status','?')) + '）')
    msg = '找到 ' + str(len(all_tasks)) + ' 个相关任务，回复序号选择：\n' + '\n'.join(lines)
    op_id = str(uuid.uuid4())[:8]
    pending_ops[op_id] = {'type': 'delete_select', 'tasks': all_tasks[:10], 'count': len(all_tasks)}
    return {'intent': 'delete', 'result': msg, 'deleted_count': 0, 'pending_op_id': op_id, 'needs_confirmation': True}


def do_update(search_condition, new_status, new_deadline=''):
    """更新任务状态/截止时间。多匹配时列出选项让用户选择。"""
    if not new_status and not new_deadline:
        return {'error': '没有提供需要更新的字段'}, 400
    updates = {}
    if new_status and new_status.strip(): updates['status'] = new_status.strip()
    if new_deadline and new_deadline.strip(): updates['deadline'] = new_deadline.strip()
    if not updates:
        return {'error': '没有提供需要更新的字段'}, 400
    r = db.supabase.table('records').select('*').like('action', f'%{search_condition[:20]}%').order('created_at', desc=True).limit(10).execute()
    if not r.data:
        return {'intent': 'update', 'result': '没有找到匹配的任务。'}
    if len(r.data) == 1:
        t = r.data[0]
        db.supabase.table('records').update(updates).eq('id', t['id']).execute()
        changed = ', '.join(f'{k}={v}' for k, v in updates.items())
        return {'intent': 'update', 'result': '已更新「' + str(t.get('action','')) + '」: ' + changed, 'new_status': new_status, 'new_deadline': new_deadline}
    # ★ 多个匹配 → 列出选项让用户选择（与 do_delete 一致）
    lines = []
    for i, t in enumerate(r.data[:10], 1):
        who = str(t.get('name', '?'))
        what = str(t.get('action', '?'))
        st = str(t.get('status', '?'))
        dl = str(t.get('deadline', '无'))
        lines.append(f"{i}. {who}：{what}（{st}，截止：{dl}）")
    nl = chr(10)
    op_id = str(uuid.uuid4())[:8]
    # 存入 pending_ops，等用户选序号
    pending_ops[op_id] = {'type': 'update_select', 'tasks': r.data[:10], 'updates': updates}
    msg = f"找到 {len(r.data)} 个匹配任务，回复序号选择要更新哪一个：" + nl + nl.join(lines)
    return {'intent': 'update', 'result': msg, 'pending_op_id': op_id, 'needs_confirmation': True}


@app.route('/voice', methods=['POST'])
def voice_input():
    return jsonify({
        "status": "not_implemented",
        "message": "语音输入功能尚未实现，敬请期待。"
    }), 501


# ================= 用户登录与权限管理 =================

# ================= 小组管理 API =================

@app.route('/api/teams')
def api_teams():
    """查询小组：返回是否存在 + 成员列表"""
    team_name = request.args.get('team_name', '').strip()
    if not team_name:
        return jsonify({'error': '缺少 team_name'}), 400
    team = db.get_team(team_name)
    if not team:
        return jsonify({'exists': False, 'members': []})
    members = db.get_team_members(team_name)
    return jsonify({'exists': True, 'team_id': team['id'], 'members': members})


@app.route('/api/teams/create', methods=['POST'])
def api_teams_create():
    """创建新小组"""
    data = request.get_json()
    if not data or not all(k in data for k in ('team_name', 'admin_name')):
        return jsonify({'error': '缺少 team_name 或 admin_name'}), 400
    tn = data['team_name'].strip()
    an = data['admin_name'].strip()
    pw = data.get('password', '123456')
    if not tn or not an:
        return jsonify({'error': '小组名和管理员名不能为空'}), 400
    existing = db.get_team(tn)
    if existing:
        return jsonify({'error': '小组已存在'}), 409
    tid = db.create_team(tn, an, pw)
    if tid:
        return jsonify({'success': True, 'team_id': tid, 'message': f'小组 {tn} 创建成功，管理员：{an}'})
    return jsonify({'error': '创建失败'}), 500


@app.route('/api/teams/disband', methods=['POST'])
def api_teams_disband():
    """
    管理员注销/解散小组：验证密码后删除小组及所有数据。
    """
    data = request.get_json()
    if not data or not all(k in data for k in ('team_name', 'admin_name', 'password')):
        return jsonify({'error': '缺少参数'}), 400
    tn = data['team_name'].strip()
    an = data['admin_name'].strip()
    pw = data['password'].strip()

    team = db.get_team(tn)
    if not team:
        return jsonify({'error': '小组不存在'}), 404

    # 验证管理员
    user = db.get_user_in_team(an, tn)
    if not user or not user.get('is_admin'):
        return jsonify({'error': '仅小组管理员可注销小组'}), 403

    ok, _ = db.verify_password(an, pw)
    if not ok:
        return jsonify({'error': '密码错误'}), 401

    tid = team['id']
    errors = []
    for table, col in [('records', 'team_id'), ('users', 'team_id'), ('teams', 'id')]:
        try:
            if col == 'id':
                db.supabase.table(table).delete().eq('id', tid).execute()
            else:
                db.supabase.table(table).delete().eq(col, tid).execute()
        except Exception as e:
            errors.append(f'{table}: {e}')
    # 尝试清理 notifications（可能没有 team_id 列）
    try:
        db.supabase.table('notifications').delete().eq('team_id', tid).execute()
    except Exception:
        pass
    if errors:
        print(f'[DISBAND] 部分删除失败: {errors}')

    return jsonify({'success': True, 'message': f'小组 {tn} 已注销，所有数据已清除'})


@app.route('/api/users/change-name', methods=['POST'])
def api_users_change_name():
    """修改用户名"""
    data = request.get_json()
    if not data or not all(k in data for k in ('old_name', 'new_name')):
        return jsonify({'error': '缺少参数'}), 400
    old = data['old_name'].strip()
    new = data['new_name'].strip()
    if not old or not new:
        return jsonify({'error': '姓名不能为空'}), 400
    # 仅管理员可修改名称
    user = db.get_user(old)
    if not user or not user.get('is_admin'):
        return jsonify({'error': '仅管理员可修改名称'}), 403
    try:
        db.supabase.table('users').update({'name': new}).eq('name', old).execute()
        # 同步更新 records 表中的 name
        db.supabase.table('records').update({'name': new}).eq('name', old).execute()
        return jsonify({'success': True, 'message': f'已更名为 {new}'})
    except Exception as e:
        return jsonify({'error': f'修改失败: {e}'}), 500


# ================= 用户登录（支持小组选择） =================

@app.route('/api/login', methods=['POST'])
def api_login():
    """
    用户登录：支持 team_name + name + password。
    """
    data = request.get_json()
    if not data or 'name' not in data:
        return jsonify({'success': False, 'error': '缺少 name 字段'}), 400

    name = data['name'].strip()
    team_name = data.get('team_name', '默认小组').strip()
    password = data.get('password', '').strip()
    if not name:
        return jsonify({'success': False, 'error': '姓名不能为空'}), 400

    # 在指定小组中查用户
    user = db.get_user_in_team(name, team_name)
    # 兼容：如果 team 查询失败，回退到全局查询
    if not user:
        user = db.get_user(name)

    if not user:
        return jsonify({'success': False, 'error': f'用户 {name} 在小组 {team_name} 中不存在'}), 404

    # 自动迁移旧数据
    if not user.get('password_hash'):
        db.update_password(name, '123456')
        print(f"[LOGIN] 用户 {name} 密码为空，已自动迁移")
        return jsonify({'success': True, 'user': {
            'name': user['name'], 'is_admin': user['is_admin'],
            'can_create': user['can_create'], 'can_remind': user['can_remind'],
            'has_security': user.get('has_security', False),
            'team_name': team_name
        }, 'message': '系统已为您设置默认密码 123456，请登录后及时修改。'})

    if not password:
        return jsonify({'success': False, 'error': '请输入密码'}), 400

    ok, _ = db.verify_password(name, password)
    if not ok:
        return jsonify({'success': False, 'error': '密码错误'}), 401

    return jsonify({'success': True, 'user': {
        'name': user['name'], 'is_admin': user['is_admin'],
        'can_create': user['can_create'], 'can_remind': user['can_remind'],
        'has_security': user.get('has_security', False),
        'team_name': team_name
    }})


@app.route('/api/change-password', methods=['POST'])
def api_change_password():
    """
    登录后修改密码。
    接收 {"name": "张三", "old_password": "123456", "new_password": "654321"}
    """
    data = request.get_json()
    if not data or not all(k in data for k in ('name', 'old_password', 'new_password')):
        return jsonify({'error': '缺少必要字段'}), 400

    name = data['name'].strip()
    old_pw = data['old_password']
    new_pw = data['new_password'].strip()

    if len(new_pw) < 4:
        return jsonify({'error': '新密码至少 4 位'}), 400

    ok, _ = db.verify_password(name, old_pw)
    if not ok:
        return jsonify({'error': '旧密码错误'}), 401

    db.update_password(name, new_pw)
    return jsonify({'success': True, 'message': '密码已修改'})


@app.route('/api/set-security', methods=['POST'])
def api_set_security():
    """
    设置/更新密保问题。
    接收 {"name": "张三", "question": "你的小学名称", "answer": "一小"}
    """
    data = request.get_json()
    if not data or not all(k in data for k in ('name', 'question', 'answer')):
        return jsonify({'error': '缺少必要字段'}), 400

    name = data['name'].strip()
    question = data['question'].strip()
    answer = data['answer'].strip()

    if not question or not answer:
        return jsonify({'error': '密保问题和答案不能为空'}), 400

    db.set_security_question(name, question, answer)
    return jsonify({'success': True, 'message': '密保问题已设置'})


@app.route('/api/security-question')
def api_security_question():
    """
    获取用户的密保问题（忘记密码时显示）。
    参数: ?name=张三
    """
    name = request.args.get('name', '').strip()
    if not name:
        return jsonify({'error': '缺少 name 参数'}), 400

    user = db.get_user(name)
    if not user:
        return jsonify({'error': '用户不存在'}), 404

    question = user.get('security_question', '')
    if not question:
        return jsonify({'error': '该用户未设置密保问题，请联系管理员重置密码'}), 404

    return jsonify({'question': question})


@app.route('/api/reset-password', methods=['POST'])
def api_reset_password():
    """
    忘记密码：通过密保验证后重置为 123456。
    接收 {"name": "张三", "answer": "一小"}
    """
    data = request.get_json()
    if not data or not all(k in data for k in ('name', 'answer')):
        return jsonify({'error': '缺少必要字段'}), 400

    name = data['name'].strip()
    answer = data['answer'].strip()

    ok = db.verify_security_answer(name, answer)
    if not ok:
        return jsonify({'error': '密保答案错误'}), 401

    db.update_password(name, '123456')
    return jsonify({'success': True, 'message': '密码已重置为 123456，请尽快修改密码'})


@app.route('/api/admin/reset-user-password', methods=['POST'])
def api_admin_reset_password():
    """
    管理员重置他人密码为 123456。
    接收 {"current_user": "管理员", "target_user": "李四"}
    """
    data = request.get_json()
    if not data or not all(k in data for k in ('current_user', 'target_user')):
        return jsonify({'error': '缺少必要字段'}), 400

    current_user = data['current_user'].strip()
    target_user = data['target_user'].strip()

    admin = db.get_user(current_user)
    if not admin or not admin.get('is_admin'):
        return jsonify({'error': '无权操作，仅管理员可重置他人密码'}), 403

    db.update_password(target_user, '123456')
    return jsonify({'success': True, 'message': f'已重置 {target_user} 的密码为 123456'})


@app.route('/api/users/delete', methods=['POST'])
def api_users_delete():
    """
    管理员删除成员。
    接收 {"current_user": "管理员", "target_user": "李四"}
    """
    data = request.get_json()
    if not data or not all(k in data for k in ('current_user', 'target_user')):
        return jsonify({'error': '缺少必要字段'}), 400

    current_user = data['current_user'].strip()
    target_user = data['target_user'].strip()

    admin = db.get_user(current_user)
    if not admin or not admin.get('is_admin'):
        return jsonify({'error': '无权操作，仅管理员可删除成员'}), 403

    # 不允许删除管理员自己
    target = db.get_user(target_user)
    if target and target.get('is_admin'):
        return jsonify({'error': '不能删除管理员账户'}), 400

    db.delete_user(target_user)
    return jsonify({'success': True, 'message': f'已删除用户 {target_user}'})


@app.route('/api/users')
def api_users():
    """
    获取所有用户列表（仅管理员可访问）。
    参数: ?current_user=管理员
    """
    current_user = request.args.get('current_user', '').strip()
    team_name = request.args.get('team_name', '默认小组').strip()
    if not current_user:
        return jsonify({'error': '缺少 current_user 参数'}), 400

    admin = db.get_user_in_team(current_user, team_name) or db.get_user(current_user)
    if not admin or not admin.get('is_admin'):
        return jsonify({'error': '无权访问，仅管理员可查看用户列表'}), 403

    # 只返回同组成员
    members = db.get_team_members(team_name)
    return jsonify(members or [])


@app.route('/api/users/update', methods=['POST'])
def api_users_update():
    """
    更新用户权限（仅管理员可访问）。
    接收 {"current_user": "管理员", "target_user": "李四", "can_create": true, "can_remind": false}
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': '缺少参数'}), 400

    current_user = data.get('current_user', '').strip()
    target_user = data.get('target_user', '').strip()
    if not current_user or not target_user:
        return jsonify({'error': '缺少 current_user 或 target_user'}), 400

    admin = db.get_user(current_user)
    if not admin or not admin.get('is_admin'):
        return jsonify({'error': '无权访问，仅管理员可修改权限'}), 403

    can_create = data.get('can_create')
    can_remind = data.get('can_remind')
    # 布尔值转换
    if can_create is not None:
        can_create = bool(can_create)
    if can_remind is not None:
        can_remind = bool(can_remind)

    db.update_user_permissions(target_user, can_create, can_remind)
    print(f"[API] 管理员 {current_user} 更新了 {target_user} 的权限: create={can_create}, remind={can_remind}")
    return jsonify({'success': True, 'message': f'已更新 {target_user} 的权限'})


@app.route('/api/users/add', methods=['POST'])
def api_users_add():
    """
    管理员添加新成员。
    接收 {"current_user": "管理员", "name": "王五", "can_create": true, "can_remind": true}
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': '缺少参数'}), 400

    current_user = data.get('current_user', '').strip()
    name = data.get('name', '').strip()
    if not current_user or not name:
        return jsonify({'error': '缺少 current_user 或 name'}), 400

    admin = db.get_user(current_user)
    if not admin or not admin.get('is_admin'):
        return jsonify({'error': '无权访问，仅管理员可添加成员'}), 403

    can_create = data.get('can_create', True)
    can_remind = data.get('can_remind', False)
    team_name = data.get('team_name', '默认小组')
    team = db.get_team(team_name)
    team_id = team['id'] if team else None

    ok = db.add_user(name, can_create, can_remind, team_id=team_id)
    if not ok:
        return jsonify({'success': False, 'error': f'用户 {name} 在小组 {team_name} 中已存在'})

    print(f"[API] 管理员 {current_user} 添加了新用户: {name}")
    return jsonify({'success': True, 'message': f'已添加用户 {name}'})


@app.route('/chat', methods=['POST'])
def chat():
    """
    统一对话入口。支持四种意图：add / query / delete / update。
    """
    data = request.get_json()
    if not data or 'text' not in data:
        return jsonify({'error': '缺少 text 字段'}), 400

    user_text = data['text'].strip()
    if not user_text:
        return jsonify({'error': 'text 不能为空'}), 400
    team_name = data.get('team_name', '默认小组')

    # ---- 多任务检测：一次只能处理一个任务 ----
    multitask_warning = ''
    _segments = re.split(r'[。！？；\n]+', user_text)
    _segments = [s.strip() for s in _segments if len(s.strip()) >= 5]
    if len(_segments) > 1:
        _task_re = re.compile(r'[一-鿿]{1,4}(要|需要|必须|得|想|应该|计划|打算|准备|今天|明天|后天|这周|下周)')
        _task_count = sum(1 for s in _segments if _task_re.search(s))
        if _task_count >= 2:
            multitask_warning = '⚠️ 你一口气说了多个任务，我一次只能处理一个问题，请一个一个慢慢来～\n我现在只处理第一个：\n\n'
            user_text = _segments[0]
    # ---- 多任务检测结束 ----

    # 获取上一轮 AI 回复作为上下文
    context = data.get('context', '')

    # ---- 检查是否有待处理的 dedup 操作 ----
    # 用户回复"1"或"2"来确认去重选择
    dedup_op_id = data.get('pending_op_id', '')
    if dedup_op_id and dedup_op_id in pending_ops:
        op = pending_ops[dedup_op_id]
        if op.get('type') == 'dedup_add':
            user_choice = user_text.strip()
            # 自然语言匹配：接受"是"/"对"/"更新"/"同一个"等
            is_yes = (user_choice in ('1', '更新', '是', '对', '是的', '对的', '嗯', '好', '可以', '行',
                                       '是同一个', '同一个', '一样的', '一样', '相同') or
                      (len(user_choice) <= 6 and ('更新' in user_choice or '改' in user_choice)))
            if is_yes:
                # 更新已有任务
                t = op['existing_task']
                tid = t.get('id')
                # 合并新信息
                new_deadline = op.get('new_deadline')
                updates = {'action': op.get('new_action', t.get('action'))}
                if new_deadline:
                    updates['deadline'] = new_deadline
                if op.get('new_status') and op['new_status'] != '未完成':
                    updates['status'] = op['new_status']
                db.supabase.table('records').update(updates).eq('id', int(tid)).execute()
                reply = ai_reply("你是友好的任务助理。用纯文本。",
                    f"已更新「{t.get('action','')}」的信息。一句话确认。{OUTPUT_FORMAT_RULE}")
                pending_ops.pop(dedup_op_id)
                return jsonify({'result': reply or f"已更新「{t.get('action','')}」", 'intent': 'add'})
            is_no = (user_choice in ('2', '新建', '创建', '不是', '不对', '不一样', '不同', '不不',
                                      '不是同一个', '新的', '新任务') or
                     (len(user_choice) <= 4 and user_choice.startswith('不')) or
                     ('新建' in user_choice) or ('创建' in user_choice) or ('新的' in user_choice))
            if is_no:
                # 创建全新任务
                result = do_add(op.get('new_text', user_text),
                    op.get('new_name', '未知'), op.get('new_action', user_text),
                    op.get('new_status', '未完成'), op.get('new_deadline'),
                    team_name=team_name, created_by=data.get('user',''))
                pending_ops.pop(dedup_op_id)
                return jsonify(result)
            else:
                # 无法识别 → 提示用户
                return jsonify({'result': '我没太明白，这个是同一个任务吗？是就回复「是」，不是就回复「新建」。'})

    # ---- 处理 delete_select / update_select 序号选择 ----
    if dedup_op_id and dedup_op_id in pending_ops:
        op = pending_ops[dedup_op_id]
        if op.get('type') in ('delete_select', 'update_select'):
            user_choice = user_text.strip()
            idx = None
            m = re.search(r'(\d+)', user_choice)
            if m:
                idx = int(m.group(1)) - 1
            else:
                cn_map = {'一':0,'二':1,'三':2,'四':3,'五':4,'六':5,'七':6,'八':7,'九':8,'十':9}
                for cn, i in cn_map.items():
                    if cn in user_choice:
                        idx = i; break
            if idx is not None:
                tasks = op.get('tasks', [])
                if 0 <= idx < len(tasks):
                    t = tasks[idx]
                    tid_val = t.get('id')
                    if op.get('type') == 'delete_select':
                        db.supabase.table('records').delete().eq('id', int(tid_val)).execute()
                        pending_ops.pop(dedup_op_id)
                        reply = ai_reply('你是友好的任务助理。用纯文本。',
                            '已删除：' + str(t.get('action','')) + '。一句话确认。' + OUTPUT_FORMAT_RULE)
                        return jsonify({'intent': 'delete', 'result': reply or '已删除「' + str(t.get('action','')) + '」', 'confirmed': True})
                    else:  # update_select
                        db.supabase.table('records').update(op.get('updates', {})).eq('id', int(tid_val)).execute()
                        pending_ops.pop(dedup_op_id)
                        changed = ', '.join(f'{k}={v}' for k, v in op.get('updates', {}).items())
                        reply = ai_reply('你是友好的任务助理。用纯文本。',
                            f'已更新「{t.get("action","")}」: {changed}。一句话确认。' + OUTPUT_FORMAT_RULE)
                        return jsonify({'intent': 'update', 'result': reply or f'已更新「{t.get("action","")}」: {changed}', 'confirmed': True})
            action_word = '删除' if op.get('type') == 'delete_select' else '更新'
            return jsonify({'result': f'请回复要{action_word}的任务序号（如"{action_word}2"）。'})

    # 统一意图路由
    intent, intent_data = route_intent(user_text, data.get('user', ''))

    if intent == 'chat':
        reply = chat_directly(user_text, data.get('user', '未知用户'))
        return jsonify({'result': reply, 'intent': 'chat'})

    if intent == 'complete':
        kw = intent_data.get('keyword', user_text[:20])
        tn = data.get('team_name', '默认小组')
        un = intent_data.get('user_name', data.get('user', ''))  # 优先用提取的完成人
        # 上下文解析："第一个任务" → 从上一轮回复中提取第1条
        ordinal_match = re.search(r'第\s*(\d+|[一二三四五六七八九十])\s*[个条]', user_text)
        if ordinal_match and context:
            cn_map = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}
            n_str = ordinal_match.group(1)
            n = cn_map.get(n_str, None) or (int(n_str) if n_str.isdigit() else None)
            if n:
                ctx_lines = context.split('\n')
                task_lines = [l for l in ctx_lines if re.match(r'^\d+\.\s', l.strip())]
                if n <= len(task_lines):
                    target_line = task_lines[n-1].strip()
                    # 提取任务名和负责人
                    name_match = re.search(r'^\d+\.\s*(.+?)：', target_line)
                    action_match = re.search(r'：(.+?)（', target_line)
                    if name_match and action_match:
                        ctx_name = name_match.group(1).strip()
                        ctx_action = action_match.group(1).strip()[:50]
                        # 直接在本组中搜索匹配任务并完成
                        team = db.get_team(tn)
                        tid = team['id'] if team else None
                        base = db.supabase.table('records').select('*').eq('name', ctx_name).neq('status', '已完成')
                        if tid: base = base.eq('team_id', tid)
                        r = base.like('action', f'%{ctx_action[:10]}%').order('created_at', desc=True).limit(1).execute()
                        if r.data:
                            t = r.data[0]
                            db.supabase.table('records').update({'status': '已完成'}).eq('id', t['id']).execute()
                            return jsonify({'intent': 'complete', 'result': '已将「' + str(t.get('action','')) + '」标记为完成！'})
        result, _ = handle_complete(kw, un, tn)
        return jsonify(result)

    # 非闲聊意图：复用 classify_and_extract 结果
    if context and intent in ('delete', 'update'):
        intent_data = classify_and_extract(user_text, context)
        intent = intent_data.get('intent', intent)

    if intent == 'confirm':
        # 用户确认之前反问的操作 → 执行暂存的 pending 操作
        pending_op_id = data.get('pending_op_id', '')
        op = pending_ops.pop(pending_op_id, None) if pending_op_id else None
        if op and op['type'] in ('delete', 'delete_bulk'):
            try:
                if op['type'] == 'delete_bulk':
                    count = 0
                    for tid in op.get('task_ids', []):
                        db.supabase.table('records').delete().eq('id', int(tid)).execute()
                        count += 1
                    reply = ai_reply("你是友好的任务助理。用纯文本。",
                        f"已永久删除{count}个任务。一句话确认。{OUTPUT_FORMAT_RULE}")
                    result = {"intent": "delete", "result": reply or f"已永久删除 {count} 个任务。",
                              "deleted_count": count, "confirmed": True}
                else:
                    tid = op.get('task_id')
                    db.supabase.table('records').delete().eq('id', int(tid)).execute()
                    reply = ai_reply("你是友好的任务助理。用纯文本。",
                        f"已永久删除：{op.get('target_action','')}。一句话确认。{OUTPUT_FORMAT_RULE}")
                    result = {"intent": "delete",
                              "result": reply or f"已永久删除任务：{op.get('target_action','')}",
                              "deleted_count": 1, "confirmed": True}
            except Exception as e:
                result = {'error': f'执行删除出错: {str(e)}'}, 500
        else:
            # 找不到 pending 操作（可能已过期或已执行）
            result = {
                "intent": "confirm",
                "result": "之前的操作已经处理过了，没有需要确认的内容。请告诉我新的需求～",
                "confirmed": False
            }

    elif intent == 'cancel':
        # 用户取消操作 → 清理 pending
        pending_op_id = data.get('pending_op_id', '')
        pending_ops.pop(pending_op_id, None)
        result = {
            "intent": "cancel",
            "result": "好的，已取消，没有做任何删除。还有什么需要帮忙的吗？",
            "cancelled": True
        }

    elif intent == 'query':
        question = intent_data.get('question', user_text)
        current_user = data.get('user', '')
        team_name = data.get('team_name', '默认小组')
        result = do_query(question, current_user, team_name)

    elif intent == 'delete':
        delete_condition = intent_data.get('delete_condition', user_text)
        # 上下文解析："第一个"/"第N个"
        ordinal_match = re.search(r'第\s*(\d+|[一二三四五六七八九十])\s*[个条]', delete_condition)
        if ordinal_match and context:
            cn_map = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}
            n_str = ordinal_match.group(1)
            n = cn_map.get(n_str, None) or (int(n_str) if n_str.isdigit() else None)
            if n:
                ctx_lines = context.split('\n')
                task_lines = [l for l in ctx_lines if re.match(r'^\d+\.\s', l.strip())]
                if n <= len(task_lines):
                    m = re.search(r'：(.+?)（', task_lines[n-1])
                    if m: delete_condition = m.group(1).strip()[:30]
        # 如果条件太模糊，从上下文中提取关键词
        if context and ('这个' in delete_condition or '那个' in delete_condition or len(delete_condition) < 5):
            words = re.findall(r'[一-鿿]{2,}', context)
            for w in words:
                if w not in ('这个','那个','什么','哪些','几个','所有','确定','取消','回复','删除','任务','已经','超时','注意'):
                    delete_condition = w
                    break
        for filler in ['的这个任务','那个任务','这个任务','那个任务','这个','那个','的任务','一下','帮我','请','把','删掉','删除','删除掉','去掉','移除','取消']:
            delete_condition = delete_condition.replace(filler, '')
        result = do_delete(delete_condition.strip(), data.get('team_name', '默认小组'))

    elif intent == 'update':
        search_condition = intent_data.get('search_condition', user_text)
        new_status = intent_data.get('new_status', '')
        new_deadline = intent_data.get('new_deadline', '')
        result = do_update(search_condition, new_status, new_deadline)

    else:  # add（含智能更新 + 去重确认）
        # name优先用AI提取的（如"张三有任务"→张三），但"我"/"自己"→登录用户
        raw_name = intent_data.get('name', '未知')
        current_user = data.get('user', '').strip()
        if raw_name in ('我', '自己', '未知', '', None):
            name = current_user or '未知'
        else:
            name = raw_name
        action = intent_data.get('action', user_text)

        # ★ 引号精确匹配：用户用引号指定了确切任务名 → 直接用作 action
        quoted_action = _extract_quoted(user_text)
        if quoted_action:
            action = quoted_action

        status = intent_data.get('status', '未完成')
        deadline = intent_data.get('deadline')

        # ---- 代词清洗：action 中不能有"我"/"你"/"他" ----
        action = _clean_action_pronouns(action, name)

        # ---- 多人检测：A和B模式 → 为每人创建一条任务 ----
        multi_names = _extract_multi_names(user_text, current_user)
        if multi_names and len(multi_names) > 1:
            msgs = []
            for person_name in multi_names[:3]:
                r = do_add(user_text, person_name, action, status, deadline,
                           team_name=team_name, created_by=data.get('user',''))
                msgs.append(r.get('result', ''))
            result = {'intent': 'add', 'result': '\n'.join(msgs),
                      'multi_person': True, 'names': multi_names[:3]}
        # ---- 场景A：用户说"XX已完成" → 直接更新已有任务 ----
        elif status == '已完成' and name != '未知':
            task, method = _find_matching_task(name, action, team_name)
            if not task:
                task, method = _find_matching_task(name, user_text[:20], team_name)
            if task:
                tid = task.get('id')
                old_status = task.get('status', '')
                db.supabase.table('records').update({'status': '已完成'}).eq('id', int(tid)).execute()
                verified, actual = _verify_update(tid, 'status', '已完成')
                debug_info = {'matched_task_id': tid, 'match_method': method,
                    'old_status': old_status, 'new_status': actual, 'verified': verified,
                    'matched_action': task.get('action', '')[:40]}
                if verified:
                    reply = ai_reply("你是友好的任务助理。用纯文本，禁止Markdown。",
                        f"已将「{task.get('action','')}」标记为已完成。请用自然口语化确认。一句话。{OUTPUT_FORMAT_RULE}")
                    result = {'intent': 'add', 'result': reply or f"已更新「{task.get('action','')}」为已完成",
                              'action': 'updated_existing', 'debug': debug_info}
                else:
                    result = {'error': f'更新验证失败，状态未改变。', 'debug': debug_info}, 500
            else:
                result = do_add(user_text, name, action, status, deadline, team_name=team_name, created_by=data.get('user',''))

        # ---- 场景B：用户说"XX有新任务" → 查重确认 ----
        elif name != '未知' and len(action) >= 2:
            similar = _find_similar_task(name, action, team_name)
            if similar:
                # 找到相似任务 → 存入 pending_ops，反问用户
                op_id = str(uuid.uuid4())[:8]
                pending_ops[op_id] = {
                    'type': 'dedup_add',
                    'user': data.get('user', ''),
                    'existing_task': similar,
                    'new_name': name, 'new_action': action,
                    'new_status': status, 'new_deadline': deadline,
                    'new_text': user_text,
                    'visibility': data.get('visibility', 'public'),
                    'assigned_to': data.get('assigned_to', [])
                }
                reply = ai_reply(
                    "你是友好的任务助理。用纯文本，口语化，像朋友聊天一样自然。禁止使用序号或「回复数字XX」。",
                    f"系统中已有相似任务「{similar.get('action','')}」（状态：{similar.get('status','')}），"
                    f"用户刚才想录入的任务是「{action}」。"
                    f"请自然地反问用户这两个是不是同一个任务。"
                    f"如果是同一个任务，建议更新已有的；如果不是，就新建。语气要自然友善。"
                    f"暗示用户回复「是」或「不是」即可。{OUTPUT_FORMAT_RULE}",
                    temperature=0.8, max_tokens=200
                )
                result = {'intent': 'add', 'result': reply or '找到相似任务，请选择操作。',
                          'needs_dedup_choice': True, 'pending_op_id': op_id}
            else:
                result = do_add(user_text, name, action, status, deadline, team_name=team_name, created_by=data.get('user',''))
        else:
            result = do_add(user_text, name, action, status, deadline, team_name=team_name, created_by=data.get('user',''))

    # 多任务警告前缀
    if multitask_warning:
        def _prepend(r):
            if isinstance(r, dict) and 'result' in r:
                r = dict(r)
                r['result'] = multitask_warning + r['result']
            return r
        if isinstance(result, tuple):
            result = (_prepend(result[0]), result[1])
        elif isinstance(result, dict):
            result = _prepend(result)
    if isinstance(result, tuple):
        return jsonify(result[0]), result[1]
    if isinstance(result, dict) and 'error' in result:
        return jsonify({'result': '❌ ' + result['error'], 'intent': result.get('intent', 'add')})
    return jsonify(result)


@app.route('/add', methods=['POST'])
def add_record():
    data = request.get_json()
    user_text = data.get('text', '')

    # 权限校验：检查当前用户是否有布置任务的权限
    current_user = data.get('user', '')
    if current_user:
        user_info = db.get_user(current_user)
        if user_info and not user_info.get('can_create', True):
            return jsonify({'error': '你无权布置任务', 'status': 'forbidden'}), 403

    # 任务可见性：public=所有人可见，private=指定人员
    visibility = data.get('visibility', 'public')
    is_public = (visibility != 'private')
    assigned_to_list = data.get('assigned_to', [])
    assigned_to = ','.join(assigned_to_list) if not is_public and assigned_to_list else ''

    # 支持快速布置：如果前端直接传了 task_name/deadline，跳过AI解析
    direct_name = data.get('task_name', '').strip()
    direct_deadline = data.get('deadline', '').strip()
    if direct_name and user_text:
        task_name = direct_name
        action = user_text  # 直接用输入内容作为action
        status = '未完成'
        deadline = direct_deadline if direct_deadline else None
    else:
        parsed = parse_with_ai(user_text)
        raw_name = parsed.get('name', '未知')
        if raw_name in ('我', '自己', '未知', '', None):
            task_name = current_user or '未知'
        else:
            task_name = raw_name
        action = parsed.get('action', user_text)
        status = parsed.get('status', '未完成')
        deadline = parsed.get('deadline')
    team_name = data.get('team_name', '默认小组')
    result = do_add(user_text, task_name, action, status, deadline,
                    created_by=current_user, is_public=is_public, assigned_to=assigned_to, team_name=team_name)
    if isinstance(result, dict) and 'error' in result:
        return jsonify({'error': result['error']}), 400
    return jsonify(result)


@app.route('/query', methods=['POST'])
def query():
    data = request.get_json()
    if not data or 'text' not in data:
        return jsonify({'error': '缺少 text 字段'}), 400
    result = do_query(data['text'].strip(), data.get('user', ''))
    if isinstance(result, tuple):
        return jsonify(result[0]), result[1]
    if isinstance(result, dict) and 'error' in result:
        return jsonify({'result': '❌ ' + result['error'], 'intent': result.get('intent', 'add')})
    return jsonify(result)


# ================= 任务更新接口 =================

@app.route('/update', methods=['POST'])
def update_record():
    """
    更新已有任务。AI 解析更新意图，找到匹配任务并修改字段。
    接收 {"user": "张三", "text": "这个任务今日截止"}
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': '缺少参数'}), 400

    user_text = data.get('text', '').strip()
    current_user = data.get('user', '').strip()

    if not user_text:
        return jsonify({'error': 'text 不能为空'}), 400

    # AI 解析更新意图
    now = datetime.now()
    parse_prompt = f"""当前日期时间：{now.strftime('%Y-%m-%d %H:%M')}

用户说："{user_text}"
当前用户名：{current_user}

用户想要修改已有任务。请提取：
- target: 要修改哪个任务的关键词（如"这个任务"写成空字符串表示最近一条；"阅读报告"表示匹配action包含该词的任务）
- field: 要修改的字段（deadline 或 status）
- value: 新值。deadline格式YYYY-MM-DD HH:MM（按add的规则转换相对时间）；status为"已完成"/"未完成"/"进行中"

deadline转换规则：
- "今天"/"今日截止"/"今天完成" → {now.strftime('%Y-%m-%d')} 23:59
- "明天"/"明日" → {(now+timedelta(days=1)).strftime('%Y-%m-%d')} 23:59
- "后天" → {(now+timedelta(days=2)).strftime('%Y-%m-%d')} 23:59

返回纯JSON：{{"target":"","field":"deadline","value":"YYYY-MM-DD HH:MM"}}
"""
    intent_json = ai_reply("你是一个任务解析专家。只返回JSON。", parse_prompt, temperature=0, max_tokens=150)
    if not intent_json:
        return jsonify({'error': 'AI 解析失败'}), 500

    try:
        intent = json.loads(intent_json.replace('```json','').replace('```','').strip())
    except Exception:
        return jsonify({'error': 'AI 返回格式错误'}), 500

    target = intent.get('target', '')
    field = intent.get('field', 'deadline')
    value = intent.get('value', '')

    if not value:
        return jsonify({'error': '未能提取新值，请说得更具体些'}), 400

    # 三层匹配查找任务
    task, method = None, None
    team_name = data.get('team_name', '默认小组')
    if target:
        task, method = _find_matching_task(current_user, target, team_name)
    if not task:
        # "这个任务" → 取当前用户最近一条记录
        rows, cols = db.query(
            "SELECT * FROM records WHERE name=? ORDER BY created_at DESC LIMIT 1",
            (current_user,)
        )
        if rows:
            task = dict(zip(cols, rows[0]))
            method = 'latest'

    if not task:
        return jsonify({'error': f'没有找到匹配的任务。请说得更具体些，比如"把{current_user}的XX任务改成..."'}), 404

    task_id = task.get('id')
    old_value = task.get(field, '')

    # 执行更新（优先 Supabase SDK）
    def _do_update_db(field, val):
        if db.supabase:
            try:
                db.supabase.table('records').update({field: val}).eq('id', int(task_id)).execute()
                return
            except Exception:
                pass
        db.execute(f"UPDATE records SET {field}=? WHERE id=?", (val, int(task_id)))

    if field == 'deadline':
        validated = validate_deadline(value)
        if not validated:
            return jsonify({'error': f'日期格式无法识别: {value}'}), 400
        _do_update_db('deadline', validated)
        verified, actual = _verify_update(task_id, 'deadline', validated)
        debug = {'matched_task_id': task_id, 'match_method': method, 'old_deadline': old_value, 'new_deadline': actual, 'verified': verified, 'matched_action': task.get('action','')[:40]}
        if verified:
            reply = ai_reply("你是友好的任务助理。用纯文本，禁止Markdown。",
                f"已把「{task.get('action','')}」的截止时间更新为 {validated}。一句话确认。{OUTPUT_FORMAT_RULE}")
            return jsonify({'success': True, 'result': reply or f"已更新", 'field': 'deadline', 'value': validated, 'debug': debug})
        else:
            return jsonify({'error': f'更新验证失败: 期望={validated}, 实际={actual}', 'debug': debug}), 500

    elif field == 'status':
        _do_update_db('status', value)
        verified, actual = _verify_update(task_id, 'status', value)
        debug = {'matched_task_id': task_id, 'match_method': method, 'old_status': old_value, 'new_status': actual, 'verified': verified, 'matched_action': task.get('action','')[:40]}
        if verified:
            reply = ai_reply("你是友好的任务助理。用纯文本，禁止Markdown。",
                f"已把「{task.get('action','')}」的状态更新为「{value}」。一句话确认。{OUTPUT_FORMAT_RULE}")
            return jsonify({'success': True, 'result': reply or f"已更新", 'field': 'status', 'value': value, 'debug': debug})
        else:
            return jsonify({'error': f'更新验证失败: 期望={value}, 实际={actual}', 'debug': debug}), 500
    else:
        return jsonify({'error': f'不支持的字段: {field}'}), 400


# ====================================================================
# 看板 API（跨地域团队协作）
# ====================================================================

@app.route('/api/tasks')
def api_tasks():
    """
    获取所有任务（按 deadline 升序）。
    可选参数 ?user=xxx 过滤指定负责人的任务。

    使用 Supabase SDK 直连。
    """
    user_filter = request.args.get('user', '').strip()
    viewer = request.args.get('viewer', '').strip()
    sort_mode = request.args.get('sort', 'default').strip()
    search_kw = request.args.get('search', '').strip()
    team_name = request.args.get('team_name', '默认小组').strip()
    now = datetime.now()
    rows, cols = [], []

    viewer_is_admin = False
    if viewer:
        v = db.get_user(viewer)
        if v:
            viewer_is_admin = v.get('is_admin', False)

    # 获取小组ID
    team = db.get_team(team_name) if team_name else None
    team_id = team['id'] if team else None

    # 获取所有任务（不排序，Python 端统一排序）
    if db.supabase:
        try:
            query = db.supabase.table('records').select('*')
            # "我的任务"：不做 Supabase 过滤，改为 Python 端过滤
            if team_id:
                query = query.eq('team_id', team_id)
            result = query.execute()
            data = result.data or []
            if data:
                cols = list(data[0].keys())
                rows = [tuple(row.get(c) for c in cols) for row in data]
                print(f"[API] /api/tasks: Supabase 返回 {len(rows)} 条任务")
        except Exception as e:
            print(f"[API] /api/tasks: Supabase 查询失败({e})")

    tasks_raw = []
    for row in rows:
        d = dict(zip(cols, row))
        # "我的任务"过滤：仅自己的 + 全体 + 分配到的
        if user_filter:
            d['_visible'] = (
                str(d.get('name','')) == user_filter or
                str(d.get('name','')) in ('', '全体', '所有人') or
                user_filter in [x.strip() for x in str(d.get('assigned_to','')).split(',') if x.strip()]
            )

        # 可见性过滤
        if not viewer_is_admin and viewer:
            is_public = d.get('is_public')
            if isinstance(is_public, (int, float)):
                is_public = bool(is_public)
            if not is_public:
                assigned = str(d.get('assigned_to', '') or '')
                if not assigned:
                    continue
                names = [n.strip() for n in assigned.split(',') if n.strip()]
                if viewer not in names:
                    continue
        # 超时检测
        d['is_overdue'] = False
        d['overdue_hours'] = 0
        if d.get('deadline') and str(d['deadline']).strip():
            if str(d.get('status', '')).strip() not in ('已完成', '完成'):
                dl_str = str(d['deadline']).strip()
                delta = None
                for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
                    try:
                        dl = datetime.strptime(dl_str, fmt)
                        if dl < now:
                            d['is_overdue'] = True
                            delta = now - dl
                        break
                    except ValueError:
                        continue
                if delta:
                    d['overdue_hours'] = round(delta.total_seconds() / 3600, 1)
        # "我的任务"过滤
        if user_filter and not d.get('_visible', True):
            continue
        d.pop('_visible', None)
        # 排序辅助字段
        d['_sort_deadline'] = d.get('deadline') or '9999-12-31'
        d['_sort_created'] = d.get('created_at') or ''
        d['_is_done'] = (str(d.get('status', '')).strip() in ('已完成', '完成'))
        # 搜索过滤：匹配 name / action / deadline / status
        if search_kw:
            sk = search_kw.lower()
            haystack = (str(d.get('name','')) + ' ' + str(d.get('action','')) + ' ' +
                        str(d.get('deadline','')) + ' ' + str(d.get('status',''))).lower()
            if sk not in haystack:
                continue
        tasks_raw.append(d)

    # Python 端统一排序
    if sort_mode == 'time':
        # 时间排序：created_at 降序
        tasks_raw.sort(key=lambda x: x['_sort_created'], reverse=True)
    else:
        # 智能排序：超时优先 → 未完成其次 → 已完成最后；同状态内 deadline 升序
        def smart_key(t):
            if t['is_overdue']:
                group = 0  # 超时最前
            elif t['_is_done']:
                group = 2  # 已完成最后
            else:
                group = 1  # 未完成中间
            return (group, t['_sort_deadline'])
        tasks_raw.sort(key=smart_key)

    # 清理辅助字段
    tasks = []
    for t in tasks_raw:
        for k in ('_sort_deadline', '_sort_created', '_is_done'):
            t.pop(k, None)
        tasks.append(t)
    return jsonify(tasks)


@app.route('/api/tasks/delete', methods=['POST'])
def api_delete_task():
    """删除指定任务"""
    data = request.get_json()
    if not data or 'id' not in data:
        return jsonify({'error': '缺少任务 id'}), 400
    task_id = int(data['id'])
    try:
        if db.supabase:
            db.supabase.table('records').delete().eq('id', task_id).execute()
        else:
            db.execute("DELETE FROM records WHERE id=?", (task_id,))
        return jsonify({'success': True, 'message': '任务已删除'})
    except Exception as e:
        return jsonify({'error': f'删除失败: {str(e)}'}), 500


@app.route('/api/tasks/complete', methods=['POST'])
def api_complete_task():
    """将指定任务标记为已完成"""
    data = request.get_json()
    if not data or 'id' not in data:
        return jsonify({'error': '缺少任务 id'}), 400
    task_id = int(data['id'])

    # 优先 Supabase SDK
    try:
        if db.supabase:
            db.supabase.table('records').update({'status': '已完成'}).eq('id', task_id).execute()
            print(f"[API] /api/tasks/complete: Supabase 更新 task {task_id}")
            return jsonify({'success': True, 'message': '任务已标记为已完成'})
    except Exception as e:
        print(f"[API] /api/tasks/complete: Supabase 失败({e})，降级 SQLite")

    # 降级 SQLite
    try:
        db.execute("UPDATE records SET status='已完成' WHERE id=?", (task_id,))
        return jsonify({'success': True, 'message': '任务已标记为已完成'})
    except Exception as e:
        return jsonify({'error': f'更新失败: {str(e)}'}), 500


@app.route('/api/remind', methods=['POST'])
def api_remind():
    """
    发送催促通知。
    接收 {"task_id": 1, "admin": "管理员A"}
    向 notifications 表插入记录，target_user 为任务对应的 name。
    若任务已超时，消息追加"（已超时）"。
    """
    data = request.get_json()
    if not data or 'task_id' not in data:
        return jsonify({'error': '缺少 task_id'}), 400

    task_id = int(data['task_id'])
    # 支持两种传参方式：current_user（新）和 admin（兼容旧版）
    current_user = data.get('current_user', '') or data.get('admin', '系统')

    # 权限校验：检查是否有催促权限
    if current_user and current_user != '系统':
        user_info = db.get_user(current_user)
        if user_info and not user_info.get('can_remind', False):
            return jsonify({'error': '你无权催促他人'}), 403

    # 查询任务信息（优先 Supabase SDK 直连，跳过 SQL 解析器）
    task = None
    if db.supabase:
        try:
            result = db.supabase.table('records').select('name, action, deadline, status').eq('id', task_id).execute()
            if result.data:
                task = result.data[0]
                print(f"[API] /api/remind: Supabase 找到 task {task_id}")
        except Exception as e:
            print(f"[API] /api/remind: Supabase 查询失败({e})，降级 SQLite")

    # 降级 SQLite
    if not task:
        rows, cols = db.query(
            "SELECT name, action, deadline, status FROM records WHERE id=?",
            (task_id,)
        )
        if rows:
            task = dict(zip(cols, rows[0]))

    if not task:
        return jsonify({'error': '任务不存在'}), 404

    target_user = task.get('name', '未知')
    action = task.get('action', '未知任务')

    # 构建消息
    message = f"{current_user} 提醒你尽快完成：{action}"
    # 检查是否超时
    deadline_str = task.get('deadline', '')
    if deadline_str and str(deadline_str).strip():
        if str(task.get('status', '')).strip() not in ('已完成', '完成'):
            try:
                dl = datetime.strptime(str(deadline_str).strip(), '%Y-%m-%d %H:%M')
                if dl < datetime.now():
                    message += " （已超时）"
            except ValueError:
                pass

    nid = db.insert_notification(task_id, target_user, message)
    return jsonify({
        'success': True,
        'notification_id': nid,
        'target_user': target_user,
        'message': message
    })


@app.route('/api/notifications')
def api_notifications():
    """
    获取指定用户的未读通知列表。
    参数: ?user=xxx
    """
    user = request.args.get('user', '').strip()
    if not user:
        return jsonify({'error': '缺少 user 参数'}), 400
    notifications = db.get_notifications(user)
    return jsonify(notifications)


@app.route('/api/notifications/read', methods=['POST'])
def api_notifications_read():
    """
    标记通知已读。
    接收 {"ids": [1,2]} 或 {"all": true, "user": "张三"}
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': '缺少参数'}), 400

    if data.get('all') and data.get('user'):
        db.mark_notifications_read(all_for_user=data['user'])
    elif data.get('ids'):
        db.mark_notifications_read(ids=data['ids'])
    else:
        return jsonify({'error': '请提供 ids 或 all+user'}), 400

    return jsonify({'success': True})


if __name__ == '__main__':
    # 打印本机 IP 和公网 IP，方便局域网协作
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    print(f"[NET] 本机局域网 IP: {local_ip}")
    try:
        public_ip = http_requests.get('https://api.ipify.org', timeout=5).text
        print(f"[NET] 公网 IP: {public_ip}")
    except Exception:
        print("[NET] 公网 IP: 获取失败（可能离线）")
    print(f"[NET] 访问地址: http://{local_ip}:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)
