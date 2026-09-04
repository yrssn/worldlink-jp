
SELECT COUNT(*) FROM influencers WHERE owner_id = 5;
SELECT COUNT(*) FROM influencer_social_accounts a
  JOIN influencers i ON i.id = a.influencer_id WHERE i.owner_id = 5;

-- 1. 备份（可选，回滚用）
CREATE TABLE bak_influencers_owner5 AS SELECT * FROM influencers WHERE owner_id = 5;
CREATE TABLE bak_isa_owner5 AS
  SELECT a.* FROM influencer_social_accounts a
  JOIN influencers i ON i.id = a.influencer_id WHERE i.owner_id = 5;

-- 2. 清理
START TRANSACTION;
DELETE a FROM influencer_social_accounts a
  JOIN influencers i ON i.id = a.influencer_id
 WHERE i.owner_id = 5;
DELETE FROM influencers WHERE owner_id = 5;
-- 重新导入时若想让链接能重新匹配/不被旧任务干扰，一并清掉该用户的抓取任务：
DELETE FROM influencer_scrape_tasks WHERE owner_id = 5;
COMMIT;
