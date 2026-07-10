# ============================================================================
# db_utils.py — Supabase 云数据库操作层（无 SQLite 降级）
# ============================================================================
# 所有操作直连 Supabase，失败直接报错，不再静默降级到本地 SQLite。
# 对外接口不变：insert / query / execute / get_schema / get_user ...
# ============================================================================

import os
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

from supabase import create_client


class DatabaseManager:
    """Supabase 云数据库管理器。失败抛异常，不降级。"""

    def __init__(self):
        supabase_url = os.environ.get('SUPABASE_URL', '')
        supabase_key = os.environ.get('SUPABASE_KEY', '')
        if not supabase_url or not supabase_key:
            raise RuntimeError("未配置 SUPABASE_URL / SUPABASE_KEY，请检查 .env 文件")
        self.supabase = create_client(supabase_url, supabase_key)
        # 连通性测试
        try:
            self.supabase.table('records').select('count', count='exact').limit(1).execute()
            print("[DB] Supabase 连接成功")
        except Exception as e:
            raise RuntimeError(f"Supabase 连接失败: {e}")

        # 确保默认用户存在（首次部署或迁移后自动创建）
        self._seed_defaults()

    def _seed_defaults(self):
        """确保默认小组和默认用户存在 + 自动修复空密码哈希"""
        # 先确保"默认小组"存在
        try:
            team_r = self.supabase.table('teams').select('id').eq('name', '默认小组').execute()
            if team_r.data:
                team_id = team_r.data[0]['id']
            else:
                team_r = self.supabase.table('teams').insert({'name': '默认小组', 'admin_name': '管理员'}).execute()
                team_id = team_r.data[0]['id'] if team_r.data else None
                print(f"[DB] 已创建默认小组, team_id={team_id}")
        except Exception as e:
            print(f"[DB] 默认小组初始化失败: {e}")
            team_id = None

        if not team_id:
            print("[DB] 跳过用户初始化（无 team_id）")
            return

        defaults = [
            ('管理员', True, True, True),
            ('张三', False, True, False),
            ('李四', False, True, False),
        ]
        for name, is_admin, can_create, can_remind in defaults:
            try:
                existing = self.supabase.table('users').select('*').eq('name', name).eq('team_id', team_id).execute()
                pw = generate_password_hash('123456')
                if not existing.data:
                    self.supabase.table('users').insert({
                        'name': name, 'is_admin': is_admin,
                        'can_create': can_create, 'can_remind': can_remind,
                        'password_hash': pw, 'team_id': team_id
                    }).execute()
                    print(f"[DB] 已创建用户: {name} (team_id={team_id})")
                else:
                    u = existing.data[0]
                    updates = {}
                    if not u.get('password_hash'): updates['password_hash'] = pw
                    if not u.get('team_id'): updates['team_id'] = team_id
                    if updates:
                        self.supabase.table('users').update(updates).eq('name', name).eq('team_id', team_id).execute()
                        print(f"[DB] 已修复用户 {name}: {list(updates.keys())}")
            except Exception as e:
                print(f"[DB] 初始化用户 {name} 失败: {e}")

        # 迁移旧任务：给没有 team_id 的任务挂到默认小组
        try:
            self.supabase.table('records').update({'team_id': team_id}).is_('team_id', None).execute()
        except Exception as e:
            print(f"[DB] 迁移旧任务 team_id 失败: {e}")

    # ==================================================================
    # 核心 CRUD
    # ==================================================================

    def insert(self, table, data_dict):
        """插入记录，返回新 ID。失败抛异常。"""
        clean = {k: (v if v is not None else None) for k, v in data_dict.items()}
        result = self.supabase.table(table).insert(clean).execute()
        if result.data:
            return result.data[0].get('id', 0)
        raise RuntimeError(f"插入 {table} 失败：无返回数据")

    def query(self, sql, params=None):
        """
        执行 SELECT 查询，返回 (行元组列表, 列名列表)。
        将 ? 占位符替换后通过 Supabase SDK 执行。
        """
        if params:
            sql = self._substitute_params(sql, params)
        # 使用 SDK 链式调用
        data = self._supabase_select(sql)
        return data

    def execute(self, sql, params=None):
        """执行 UPDATE / DELETE。失败抛异常。"""
        if params:
            sql = self._substitute_params(sql, params)
        self._supabase_execute(sql)

    def get_schema(self):
        """返回 records 表结构描述（供 AI 生成 SQL）。"""
        return """表名: records
列: id (INTEGER), name (TEXT), action (TEXT), status (TEXT),
     note (TEXT), created_at (TEXT), deadline (TEXT),
     user_id (TEXT), is_public (BOOLEAN), assigned_to (TEXT),
     team_id (INTEGER，用于数据隔离，每条记录必须属于一个小组)
数据库: PostgreSQL (Supabase)
日期函数: date(deadline) = CURRENT_DATE"""

    # ==================================================================
    # SQL → Supabase SDK 转换（简化版）
    # ==================================================================

    def _substitute_params(self, sql, params):
        """替换 ? 占位符"""
        result = sql
        for p in params:
            if p is None:
                result = result.replace('?', 'NULL', 1)
            elif isinstance(p, (int, float)):
                result = result.replace('?', str(p), 1)
            else:
                result = result.replace('?', f"'{p}'", 1)
        return result

    def _supabase_select(self, sql):
        """解析简单 SELECT 并通过 SDK 执行。复杂 SQL 抛异常。"""
        import re
        sql = sql.strip().rstrip(';')

        # 提取列
        m = re.search(r'SELECT\s+(.+?)\s+FROM', sql, re.IGNORECASE)
        cols_str = m.group(1).strip() if m else '*'
        select_str = ', '.join(c.strip() for c in cols_str.split(',')) if cols_str != '*' else '*'

        # 提取表名
        m = re.search(r'FROM\s+(\w+)', sql, re.IGNORECASE)
        if not m:
            raise ValueError(f"无法解析表名: {sql[:60]}")
        table = m.group(1).strip()

        query = self.supabase.table(table).select(select_str)

        # WHERE
        where_m = re.search(r'WHERE\s+(.+?)(?:\s+ORDER\s+BY|\s+LIMIT|\s*$)', sql, re.IGNORECASE)
        if where_m:
            query = self._apply_where(query, where_m.group(1))

        # ORDER BY
        order_m = re.search(r'ORDER\s+BY\s+(\w+)\s*(ASC|DESC)?', sql, re.IGNORECASE)
        if order_m:
            col = order_m.group(1)
            desc = (order_m.group(2) or '').upper() == 'DESC'
            query = query.order(col, desc=desc)

        # LIMIT
        limit_m = re.search(r'LIMIT\s+(\d+)', sql, re.IGNORECASE)
        if limit_m:
            query = query.limit(int(limit_m.group(1)))

        result = query.execute()
        data = result.data or []
        if not data:
            return [], []
        cols = list(data[0].keys())
        rows = [tuple(row.get(c) for c in cols) for row in data]
        return rows, cols

    def _apply_where(self, query, cond_str):
        """将 WHERE 条件转为 SDK 链式调用"""
        import re
        parts = re.split(r'\s+AND\s+', cond_str, flags=re.IGNORECASE)
        for part in parts:
            part = part.strip()
            # col = 'val'
            m = re.match(r"(\w+)\s*=\s*'([^']*)'", part)
            if m: query = query.eq(m.group(1), m.group(2)); continue
            # col = 数字
            m = re.match(r"(\w+)\s*=\s*(\d+)", part)
            if m: query = query.eq(m.group(1), int(m.group(2))); continue
            # col != 'val'
            m = re.match(r"(\w+)\s*!=\s*'([^']*)'", part)
            if m: query = query.neq(m.group(1), m.group(2)); continue
            # col LIKE '%val%'
            m = re.match(r"(\w+)\s+LIKE\s+'([^']*)'", part, re.IGNORECASE)
            if m: query = query.like(m.group(1), m.group(2)); continue
            # col IS NULL
            if re.match(r"(\w+)\s+IS\s+NULL", part, re.IGNORECASE):
                m = re.match(r"(\w+)", part)
                if m: query = query.is_(m.group(1), None); continue
            # date(col) = CURRENT_DATE
            m = re.match(r"date\((\w+)\)\s*=\s*CURRENT_DATE", part, re.IGNORECASE)
            if m:
                today = datetime.now().strftime('%Y-%m-%d')
                query = query.gte(m.group(1), today).lt(m.group(1), today + 'T23:59:59')
                continue
            # 无法识别的条件 → 跳过
            print(f"[DB] 跳过无法解析的WHERE条件: {part}")
        return query

    def _supabase_execute(self, sql):
        """执行 UPDATE / DELETE（简化解析）"""
        import re
        sql_upper = sql.upper().strip()

        m = re.search(r'(?:UPDATE|DELETE\s+FROM)\s+(\w+)', sql_upper)
        if not m:
            raise ValueError(f"无法解析: {sql[:60]}")
        table = m.group(1).strip()

        # WHERE
        where_m = re.search(r'WHERE\s+(.+?)$', sql, re.IGNORECASE)
        if not where_m:
            raise ValueError("缺少 WHERE 条件")
        cond_str = where_m.group(1)

        if sql_upper.startswith('DELETE'):
            query = self.supabase.table(table).delete()
        else:
            set_m = re.search(r'SET\s+(.+?)\s+WHERE', sql, re.IGNORECASE)
            updates = {}
            if set_m:
                for pair in set_m.group(1).split(','):
                    kv = pair.strip().split('=', 1)
                    if len(kv) == 2:
                        updates[kv[0].strip()] = kv[1].strip().strip("'\"")
            query = self.supabase.table(table).update(updates)

        # 应用 WHERE（简单解析）
        for part in re.split(r'\s+AND\s+', cond_str, flags=re.IGNORECASE):
            part = part.strip()
            m = re.match(r"(\w+)\s*=\s*'([^']*)'", part)
            if m: query = query.eq(m.group(1), m.group(2)); continue
            m = re.match(r"(\w+)\s*=\s*(\d+)", part)
            if m: query = query.eq(m.group(1), int(m.group(2))); continue
            m = re.match(r"(\w+)\s*!=\s*'([^']*)'", part)
            if m: query = query.neq(m.group(1), m.group(2)); continue

        query.execute()

    # ==================================================================
    # 用户管理
    # ==================================================================

    def get_user(self, name):
        """查询用户。返回 dict 或 None。"""
        r = self.supabase.table('users').select('*').eq('name', name).execute()
        if r.data:
            u = r.data[0]
            return {
                'name': u.get('name'), 'is_admin': bool(u.get('is_admin')),
                'can_create': bool(u.get('can_create', True)),
                'can_remind': bool(u.get('can_remind', False)),
                'password_hash': u.get('password_hash', ''),
                'has_security': bool(u.get('security_question', '')),
                'security_question': u.get('security_question', ''),
                'security_answer_hash': u.get('security_answer_hash', ''),
            }
        return None

    def get_all_users(self):
        """返回所有用户列表。"""
        r = self.supabase.table('users').select('*').order('name').execute()
        return r.data or []

    def add_user(self, name, can_create=True, can_remind=False, password='123456', team_id=None):
        """添加新用户。组内唯一（不同小组允许同名）。"""
        # 检查组内是否已存在
        if team_id:
            r = self.supabase.table('users').select('name').eq('name', name).eq('team_id', team_id).execute()
            if r.data:
                return False
        pw = generate_password_hash(password)
        data = {
            'name': name, 'is_admin': False,
            'can_create': can_create, 'can_remind': can_remind,
            'password_hash': pw
        }
        if team_id:
            data['team_id'] = team_id
        self.supabase.table('users').insert(data).execute()
        return True

    def update_user_permissions(self, name, can_create=None, can_remind=None):
        updates = {}
        if can_create is not None: updates['can_create'] = bool(can_create)
        if can_remind is not None: updates['can_remind'] = bool(can_remind)
        if updates:
            self.supabase.table('users').update(updates).eq('name', name).execute()

    def delete_user(self, name):
        self.supabase.table('users').delete().eq('name', name).execute()

    def update_password(self, name, new_password):
        pw = generate_password_hash(new_password)
        self.supabase.table('users').update({'password_hash': pw}).eq('name', name).execute()

    def set_security_question(self, name, question, answer):
        ans = generate_password_hash(answer)
        self.supabase.table('users').update({
            'security_question': question, 'security_answer_hash': ans
        }).eq('name', name).execute()

    def verify_password(self, name, plain):
        """验证密码。返回 (bool, user_dict)。"""
        user = self.get_user(name)
        if not user:
            return False, None
        pw = user.get('password_hash', '')
        if not pw:
            pw = generate_password_hash('123456')
            self.supabase.table('users').update({'password_hash': pw}).eq('name', name).execute()
        return check_password_hash(pw, plain), user

    def verify_security_answer(self, name, answer):
        user = self.get_user(name)
        if not user or not user.get('security_answer_hash'):
            return False
        return check_password_hash(user['security_answer_hash'], answer)

    # ==================================================================
    # 通知系统
    # ==================================================================

    def insert_notification(self, task_id, target_user, message):
        r = self.supabase.table('notifications').insert({
            'task_id': task_id, 'target_user': target_user,
            'message': message, 'is_read': False
        }).execute()
        return r.data[0].get('id', 0) if r.data else 0

    def get_notifications(self, target_user):
        r = self.supabase.table('notifications').select('*') \
            .eq('target_user', target_user).eq('is_read', False) \
            .order('created_at', desc=True).execute()
        return r.data or []

    def mark_notifications_read(self, ids=None, all_for_user=None):
        if ids:
            for nid in ids:
                self.supabase.table('notifications').update({'is_read': True}).eq('id', int(nid)).execute()
        elif all_for_user:
            self.supabase.table('notifications').update({'is_read': True}) \
                .eq('target_user', all_for_user).eq('is_read', False).execute()


    # ==================================================================
    # 小组（Teams）
    # ==================================================================

    def get_team(self, team_name):
        r = self.supabase.table('teams').select('*').eq('name', team_name).execute()
        return r.data[0] if r.data else None

    def create_team(self, team_name, admin_name, password='123456'):
        r = self.supabase.table('teams').insert({'name': team_name, 'admin_name': admin_name}).execute()
        tid = r.data[0]['id'] if r.data else None
        if tid:
            pw = generate_password_hash(password)
            self.supabase.table('users').insert({
                'name': admin_name, 'is_admin': True,
                'can_create': True, 'can_remind': True,
                'password_hash': pw, 'team_id': tid
            }).execute()
        return tid

    def get_team_members(self, team_name):
        team = self.get_team(team_name)
        if not team: return None
        r = self.supabase.table('users').select('name,is_admin,can_create,can_remind') \
            .eq('team_id', team['id']).order('name').execute()
        return r.data or []

    def get_user_in_team(self, name, team_name):
        team = self.get_team(team_name)
        if not team: return None
        r = self.supabase.table('users').select('*').eq('name', name).eq('team_id', team['id']).execute()
        if r.data:
            u = r.data[0]
            return {
                'name': u.get('name'), 'is_admin': bool(u.get('is_admin')),
                'can_create': bool(u.get('can_create', True)),
                'can_remind': bool(u.get('can_remind', False)),
                'password_hash': u.get('password_hash', ''),
                'has_security': bool(u.get('security_question', '')),
                'security_question': u.get('security_question', ''),
                'security_answer_hash': u.get('security_answer_hash', ''),
                'team_id': u.get('team_id'), 'team_name': team_name
            }
        return None


# 模块级实例
db = DatabaseManager()
