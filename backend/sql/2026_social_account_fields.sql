-- ============================================================================
-- 达人账号维度字段迁到 influencer_social_accounts（手工执行，不走 alembic）
--
-- 执行顺序：
--   1) 加列 / 加索引（幂等：已存在的列会报 1060，可忽略；MySQL 8 也可先查 information_schema）
--   2) 回填：influencers.fb_* → 该达人的 Facebook 关联账号（有则只补空值，无则新建）
--   3) 抓取任务表加 social_account_id（一键抓取回写到指定账号）
--   4) 可选：唯一约束（先确认没有重复行再加，否则 1062）
--
-- 主表 influencers 的 fb_* / messenger 列本次【保留不删】，仅代码层不再读写；
-- 确认稳定后再单独 DROP。
-- 建议先 `mysqldump` 备份 influencers / influencer_social_accounts。
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1) 新增列
-- ---------------------------------------------------------------------------
ALTER TABLE influencer_social_accounts
  ADD COLUMN page_id            VARCHAR(128) NULL COMMENT '平台内页面/账号 ID（原 fb_page_id）',
  ADD COLUMN author_id          VARCHAR(255) NULL COMMENT '平台内作者 ID（原 fb_author_id）',
  ADD COLUMN title              VARCHAR(255) NULL COMMENT '账号/页面名称（原 fb_page_title）',
  ADD COLUMN avatar_url         VARCHAR(512) NULL COMMENT '账号头像',
  ADD COLUMN categories         JSON         NULL COMMENT '分类（原 fb_categories）',
  ADD COLUMN likes              INT          NULL COMMENT '点赞数（原 fb_likes）',
  ADD COLUMN rating             FLOAT        NULL COMMENT '评分（原 fb_rating）',
  ADD COLUMN rating_count       INT          NULL COMMENT '评分人数（原 fb_rating_count）',
  ADD COLUMN checkins_mentions  INT          NULL COMMENT '打卡/提及数（原 fb_checkins_mentions）',
  ADD COLUMN page_created_at    DATETIME     NULL COMMENT '账号创建时间（原 fb_page_created_at）',
  ADD COLUMN ad_library_id      VARCHAR(128) NULL COMMENT '广告库 ID（原 fb_ad_library_id）',
  ADD COLUMN ad_status          VARCHAR(64)  NULL COMMENT '广告状态（原 fb_ad_status）',
  ADD COLUMN messenger          VARCHAR(255) NULL COMMENT '该账号的 Messenger / 私信入口（原主表 messenger）',
  ADD COLUMN notes              VARCHAR(512) NULL COMMENT '该账号备注',
  ADD COLUMN last_scraped_at    DATETIME     NULL COMMENT '最近一次抓取时间';

ALTER TABLE influencer_social_accounts
  ADD INDEX ix_isa_page_id (page_id),
  ADD INDEX ix_isa_url (url(191));

-- ---------------------------------------------------------------------------
-- 2) 回填 fb_* → Facebook 关联账号
--    归一化比对：忽略 http/https、www.、尾斜杠、?query/#fragment，忽略大小写
-- ---------------------------------------------------------------------------

-- 2.1 临时表：每个有 FB 资料的达人 + 归一化后的链接 + 从链接末段解析出的 handle
DROP TEMPORARY TABLE IF EXISTS tmp_fb_src;
CREATE TEMPORARY TABLE tmp_fb_src AS
SELECT
  i.id AS influencer_id,
  i.fb_page_url,
  LOWER(TRIM(TRAILING '/' FROM
    SUBSTRING_INDEX(SUBSTRING_INDEX(
      REPLACE(REPLACE(REPLACE(TRIM(i.fb_page_url), 'https://', ''), 'http://', ''), 'www.', ''),
    '?', 1), '#', 1)
  )) AS norm_url,
  NULL AS handle,
  i.fb_page_id, i.fb_author_id, i.fb_page_title, i.fb_categories,
  i.fb_followers, i.fb_likes, i.fb_rating, i.fb_rating_count,
  i.fb_checkins_mentions, i.fb_page_created_at, i.fb_ad_library_id, i.fb_ad_status,
  i.messenger
FROM influencers i
WHERE (i.fb_page_url IS NOT NULL AND i.fb_page_url <> '')
   OR (i.fb_page_id IS NOT NULL AND i.fb_page_id <> '');

-- handle：链接末段；profile.php?id=xxx 这类链接末段没意义，改用 fb_page_id
ALTER TABLE tmp_fb_src MODIFY handle VARCHAR(128) NULL;
UPDATE tmp_fb_src
   SET handle = CASE
     WHEN norm_url = '' OR norm_url LIKE '%profile.php' THEN fb_page_id
     ELSE COALESCE(NULLIF(SUBSTRING_INDEX(norm_url, '/', -1), ''), fb_page_id)
   END;

-- 2.2 现有 Facebook 账号行的归一化链接
DROP TEMPORARY TABLE IF EXISTS tmp_fb_acc;
CREATE TEMPORARY TABLE tmp_fb_acc AS
SELECT
  a.id AS account_id,
  a.influencer_id,
  LOWER(TRIM(TRAILING '/' FROM
    SUBSTRING_INDEX(SUBSTRING_INDEX(
      REPLACE(REPLACE(REPLACE(TRIM(a.url), 'https://', ''), 'http://', ''), 'www.', ''),
    '?', 1), '#', 1)
  )) AS norm_url
FROM influencer_social_accounts a
WHERE a.platform = 'facebook';

-- 2.3 已有同链接账号：只补空值，不覆盖已有值
UPDATE influencer_social_accounts a
JOIN tmp_fb_acc t ON t.account_id = a.id
JOIN tmp_fb_src s ON s.influencer_id = t.influencer_id
                 AND s.norm_url <> '' AND s.norm_url = t.norm_url
SET
  a.page_id           = COALESCE(a.page_id, s.fb_page_id),
  a.author_id         = COALESCE(a.author_id, s.fb_author_id),
  a.title             = COALESCE(a.title, s.fb_page_title),
  a.categories        = COALESCE(a.categories, s.fb_categories),
  a.followers         = COALESCE(a.followers, s.fb_followers),
  a.likes             = COALESCE(a.likes, s.fb_likes),
  a.rating            = COALESCE(a.rating, s.fb_rating),
  a.rating_count      = COALESCE(a.rating_count, s.fb_rating_count),
  a.checkins_mentions = COALESCE(a.checkins_mentions, s.fb_checkins_mentions),
  a.page_created_at   = COALESCE(a.page_created_at, s.fb_page_created_at),
  a.ad_library_id     = COALESCE(a.ad_library_id, s.fb_ad_library_id),
  a.ad_status         = COALESCE(a.ad_status, s.fb_ad_status),
  a.messenger         = COALESCE(a.messenger, s.messenger),
  a.handle            = COALESCE(a.handle, s.handle);

-- 2.4 没有匹配账号的达人：新建一条 Facebook 账号行
--     platform_id 按「平台管理」里的 code / 名称匹配 facebook，匹配不到留 NULL
INSERT INTO influencer_social_accounts
  (influencer_id, platform, platform_id, handle, url, followers,
   page_id, author_id, title, categories, likes, rating, rating_count,
   checkins_mentions, page_created_at, ad_library_id, ad_status, messenger,
   created_at, updated_at)
SELECT
  s.influencer_id,
  'facebook',
  (SELECT p.id FROM bitbrowser_platforms p
     WHERE LOWER(TRIM(p.code)) IN ('facebook', 'fb')
        OR LOWER(TRIM(p.name)) IN ('facebook', 'fb', '脸书')
     ORDER BY p.id LIMIT 1),
  s.handle,
  NULLIF(TRIM(s.fb_page_url), ''),
  s.fb_followers,
  s.fb_page_id, s.fb_author_id, s.fb_page_title, s.fb_categories,
  s.fb_likes, s.fb_rating, s.fb_rating_count,
  s.fb_checkins_mentions, s.fb_page_created_at, s.fb_ad_library_id, s.fb_ad_status,
  s.messenger,
  NOW(), NOW()
FROM tmp_fb_src s
WHERE NOT EXISTS (
  SELECT 1 FROM tmp_fb_acc t
  WHERE t.influencer_id = s.influencer_id
    AND ((s.norm_url <> '' AND t.norm_url = s.norm_url)
         -- 主表只有 fb_page_id 没链接时，只要该达人已有 FB 账号就不再新建
         OR s.norm_url = '')
);

-- 2.5 只有 page_id 没链接、且该达人已有 FB 账号：把 page_id 等补到第一条 FB 账号上
-- （MySQL 临时表在同一条语句里只能出现一次，故这里 tmp_fb_src / tmp_fb_acc 各只引用一次）
UPDATE influencer_social_accounts a
JOIN (
  SELECT t.influencer_id, MIN(t.account_id) AS account_id
  FROM tmp_fb_acc t
  GROUP BY t.influencer_id
) m ON m.account_id = a.id
JOIN tmp_fb_src s ON s.influencer_id = m.influencer_id AND s.norm_url = ''
SET
  a.page_id           = COALESCE(a.page_id, s.fb_page_id),
  a.author_id         = COALESCE(a.author_id, s.fb_author_id),
  a.title             = COALESCE(a.title, s.fb_page_title),
  a.categories        = COALESCE(a.categories, s.fb_categories),
  a.followers         = COALESCE(a.followers, s.fb_followers),
  a.likes             = COALESCE(a.likes, s.fb_likes),
  a.rating            = COALESCE(a.rating, s.fb_rating),
  a.rating_count      = COALESCE(a.rating_count, s.fb_rating_count),
  a.checkins_mentions = COALESCE(a.checkins_mentions, s.fb_checkins_mentions),
  a.page_created_at   = COALESCE(a.page_created_at, s.fb_page_created_at),
  a.ad_library_id     = COALESCE(a.ad_library_id, s.fb_ad_library_id),
  a.ad_status         = COALESCE(a.ad_status, s.fb_ad_status),
  a.messenger         = COALESCE(a.messenger, s.messenger);

-- 2.6 补齐所有账号行的 platform_id（按平台管理 code / 名称匹配，匹配不到留 NULL）
UPDATE influencer_social_accounts a
LEFT JOIN bitbrowser_platforms p
  ON LOWER(TRIM(p.code)) = a.platform
  OR (a.platform = 'facebook'   AND LOWER(TRIM(p.code)) = 'fb')
  OR (a.platform = 'instagram'  AND LOWER(TRIM(p.code)) IN ('ig', 'ins'))
  OR (a.platform = 'twitter'    AND LOWER(TRIM(p.code)) = 'x')
  OR (a.platform = 'xiaohongshu' AND LOWER(TRIM(p.code)) IN ('xhs', 'rednote'))
SET a.platform_id = p.id
WHERE a.platform_id IS NULL AND p.id IS NOT NULL;

DROP TEMPORARY TABLE IF EXISTS tmp_fb_src;
DROP TEMPORARY TABLE IF EXISTS tmp_fb_acc;

-- ---------------------------------------------------------------------------
-- 3) 抓取任务绑定目标账号（列表「一键抓取」回写到选中的关联账号）
-- ---------------------------------------------------------------------------
ALTER TABLE influencer_scrape_tasks
  ADD COLUMN social_account_id INT NULL COMMENT '一键抓取时绑定的关联账号，抓取结果回写到该账号',
  ADD INDEX ix_ist_social_account_id (social_account_id),
  ADD CONSTRAINT fk_ist_social_account
    FOREIGN KEY (social_account_id) REFERENCES influencer_social_accounts(id) ON DELETE SET NULL;

-- ---------------------------------------------------------------------------
-- 4) 校验 & 可选唯一约束
-- ---------------------------------------------------------------------------
-- 4.1 检查重复（应为空结果，否则先人工合并）
-- SELECT influencer_id, platform, handle, COUNT(*) c
--   FROM influencer_social_accounts
--  WHERE handle IS NOT NULL
--  GROUP BY influencer_id, platform, handle HAVING c > 1;

-- 4.2 确认无重复后再执行（默认不加：加了以后同一达人同平台同 handle 不能重复写入）
-- ALTER TABLE influencer_social_accounts
--   ADD UNIQUE KEY uq_isa_influencer_platform_handle (influencer_id, platform, handle);

-- 4.3 抽查回填效果
-- SELECT i.id, i.display_name, i.fb_page_url, i.fb_followers,
--        a.id AS account_id, a.url, a.handle, a.followers, a.likes, a.rating, a.title
--   FROM influencers i
--   LEFT JOIN influencer_social_accounts a ON a.influencer_id = i.id AND a.platform = 'facebook'
--  WHERE i.fb_page_url IS NOT NULL
--  ORDER BY i.id DESC LIMIT 50;
