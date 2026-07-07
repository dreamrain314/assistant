# ============================================================================
# migrate_to_supabase.py — 将本地 SQLite 数据迁移到 Supabase
# ============================================================================
# 用法:
#   1. 确保已安装依赖: pip install supabase python-dotenv
#   2. 确保 .env 中配置了 SUPABASE_URL 和 SUPABASE_KEY
#   3. 确保 Supabase 中已创建 records 表
#   4. 运行: python migrate_to_supabase.py
#
# Supabase 建表 SQL（在 Supabase Dashboard → SQL Editor 中执行）：
#   CREATE TABLE IF NOT EXISTS records (
#     id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
#     name TEXT,
#     action TEXT,
#     status TEXT,
#     note TEXT,
#     created_at TEXT,
#     deadline TEXT,
#     user_id TEXT
#   );
# ============================================================================

import sqlite3
import os
import sys
from dotenv import load_dotenv

# 加载 .env
load_dotenv()

SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ 请先在 .env 中配置 SUPABASE_URL 和 SUPABASE_KEY")
    sys.exit(1)

try:
    from supabase import create_client
except ImportError:
    print("❌ 请先安装 supabase: pip install supabase")
    sys.exit(1)

# 连接 Supabase
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# 连接本地 SQLite
sqlite_conn = sqlite3.connect('data.db')
sqlite_conn.row_factory = sqlite3.Row
cursor = sqlite_conn.cursor()

# 读取所有本地数据
cursor.execute("SELECT * FROM records ORDER BY id")
rows = cursor.fetchall()
col_names = [desc[0] for desc in cursor.description]

print(f"本地 SQLite 中有 {len(rows)} 条记录")
print(f"列: {col_names}")

if len(rows) == 0:
    print("没有数据需要迁移。")
    sqlite_conn.close()
    sys.exit(0)

# 逐条插入 Supabase
success_count = 0
fail_count = 0

for row in rows:
    data = dict(zip(col_names, row))
    # 移除 id → Supabase 自动生成
    data.pop('id', None)
    # None 值保留

    try:
        result = supabase.table('records').insert(data).execute()
        if result.data:
            new_id = result.data[0].get('id', '?')
            print(f"  ✅ [{new_id}] {data.get('name', '?')}: {data.get('action', '?')[:30]}")
            success_count += 1
        else:
            print(f"  ❌ 插入失败: {data.get('action', '?')[:30]}")
            fail_count += 1
    except Exception as e:
        print(f"  ❌ 错误: {e}")
        fail_count += 1

sqlite_conn.close()

print(f"\n迁移完成: 成功 {success_count} 条, 失败 {fail_count} 条")
print("建议: 迁移后通过 /tasks 接口验证数据完整性")
