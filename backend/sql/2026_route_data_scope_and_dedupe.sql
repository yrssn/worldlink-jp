-- 权限：角色按路由单独配置数据范围；用户：导入/批量导入按主页链接与「对照账号」区别开
-- 手动执行（不用 alembic）。MySQL 8。

-- roles.menu_data_scopes：{"<menu_code>": {"scope": "all" | "users", "user_ids": [..]}}
-- 只对写在这里的路由生效，其余路由仍按 roles.data_scope
ALTER TABLE roles ADD COLUMN menu_data_scopes JSON NULL;

-- users.dedupe_against_user_ids：[user_id, ...]
-- 导入 / 批量导入时，主页链接（归一化）已在这些用户名下的行跳过不入库
ALTER TABLE users ADD COLUMN dedupe_against_user_ids JSON NULL;
