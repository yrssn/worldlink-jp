"""Instagram Profile Scraper 对接的纯函数单元测试。

只覆盖不依赖数据库 / 网络的映射与判定逻辑，可直接运行：

    python -m unittest backend.tests.test_ig_profile_integration

或在 backend 目录下：

    python -m unittest tests.test_ig_profile_integration
"""
from __future__ import annotations

import unittest

from app.services import apify_service, influencer_service, scrape_service

# 取自 apify/instagram-profile-scraper 真实输出的精简样例
IG_PROFILE_SAMPLE = {
    "inputUrl": "https://www.instagram.com/nasa",
    "id": "528817151",
    "username": "nasa",
    "url": "https://www.instagram.com/nasa",
    "fullName": "NASA",
    "biography": "🚀 🌎 Exploring the universe and our home planet.",
    "about": {"country": "United States", "date_joined": "August 2013"},
    "followersCount": 96323377,
    "followsCount": 80,
    "postsCount": 4519,
    "isBusinessAccount": True,
    "businessCategoryName": "Government Agencies",
    "verified": True,
    "externalUrl": "https://www.nasa.gov/",
    "profilePicUrl": "https://example.com/pic.jpg",
    "profilePicUrlHD": "https://example.com/pic_hd.jpg",
}

# 取自 apify/facebook-pages-scraper 的精简样例（用于区分平台）
FB_PAGE_SAMPLE = {
    "pageName": "Humans of New York",
    "title": "Humans of New York",
    "pageUrl": "https://www.facebook.com/humansofnewyork/",
    "facebookUrl": "https://www.facebook.com/humansofnewyork/",
    "pageId": "10643211755",
    "followers": 18000000,
    "email": "hi@example.com",
}


class NormalizeIgUsernameTests(unittest.TestCase):
    def test_plain_username(self):
        self.assertEqual(apify_service.normalize_ig_username("nasa"), "nasa")

    def test_at_prefix(self):
        self.assertEqual(apify_service.normalize_ig_username("@nasa"), "nasa")

    def test_full_url(self):
        self.assertEqual(
            apify_service.normalize_ig_username("https://www.instagram.com/nasa/"),
            "nasa",
        )

    def test_url_with_query(self):
        self.assertEqual(
            apify_service.normalize_ig_username("instagram.com/natgeo?hl=en"),
            "natgeo",
        )

    def test_blank_and_invalid(self):
        self.assertIsNone(apify_service.normalize_ig_username(""))
        self.assertIsNone(apify_service.normalize_ig_username("   "))
        self.assertIsNone(
            apify_service.normalize_ig_username("https://www.instagram.com/p/")
        )


class LooksLikeInstagramTests(unittest.TestCase):
    def test_detects_instagram(self):
        self.assertTrue(influencer_service._looks_like_instagram(IG_PROFILE_SAMPLE))

    def test_facebook_is_not_instagram(self):
        self.assertFalse(influencer_service._looks_like_instagram(FB_PAGE_SAMPLE))

    def test_url_only_instagram(self):
        self.assertTrue(
            influencer_service._looks_like_instagram(
                {"username": "x", "url": "https://www.instagram.com/x"}
            )
        )

    def test_empty(self):
        self.assertFalse(influencer_service._looks_like_instagram({}))


class MapIgProfileTests(unittest.TestCase):
    def test_core_fields(self):
        mapped = influencer_service._map_ig_profile(IG_PROFILE_SAMPLE)
        self.assertEqual(mapped["display_name"], "NASA")
        self.assertEqual(mapped["real_name"], "NASA")
        self.assertEqual(mapped["bio"], IG_PROFILE_SAMPLE["biography"])
        self.assertEqual(mapped["avatar_url"], "https://example.com/pic_hd.jpg")
        self.assertEqual(mapped["website"], "https://www.nasa.gov/")
        self.assertEqual(mapped["country"], "United States")
        self.assertIs(mapped["raw_profile"], IG_PROFILE_SAMPLE)
        # 不应误填 Facebook 专属字段
        self.assertNotIn("fb_page_id", mapped)
        self.assertNotIn("fb_page_url", mapped)

    def test_handle_and_url(self):
        handle, url = influencer_service._ig_handle_url(IG_PROFILE_SAMPLE)
        self.assertEqual(handle, "nasa")
        self.assertEqual(url, "https://www.instagram.com/nasa")

    def test_handle_url_fallback(self):
        handle, url = influencer_service._ig_handle_url({"username": "natgeo"})
        self.assertEqual(handle, "natgeo")
        self.assertEqual(url, "https://www.instagram.com/natgeo")

    def test_display_name_fallback_to_username(self):
        mapped = influencer_service._map_ig_profile({"username": "natgeo"})
        self.assertEqual(mapped["display_name"], "natgeo")


class IgEvalInputTests(unittest.TestCase):
    def test_eval_input_fields(self):
        ev = scrape_service._ig_to_eval_input(IG_PROFILE_SAMPLE)
        self.assertEqual(ev["platform"], "instagram")
        self.assertEqual(ev["title"], "NASA")
        self.assertEqual(ev["username"], "nasa")
        self.assertEqual(ev["followers"], 96323377)
        self.assertEqual(ev["website"], "https://www.nasa.gov/")
        self.assertTrue(ev["is_business"])


class IgProfileToFormTests(unittest.TestCase):
    """内联「自动抓取任务」弹窗选 Instagram 时的结果映射（纯函数）。"""

    def test_form_fields(self):
        form = influencer_service.ig_profile_to_form(IG_PROFILE_SAMPLE)
        self.assertEqual(form["platform"], "instagram")
        self.assertEqual(form["display_name"], "NASA")
        self.assertEqual(form["ig_username"], "nasa")
        self.assertEqual(form["ig_url"], "https://www.instagram.com/nasa")
        self.assertEqual(form["followers"], 96323377)
        self.assertEqual(form["website"], "https://www.nasa.gov/")
        # 原始资料精简保留，供存库按 IG 用户名/主页 URL 去重
        self.assertEqual(form["_ig_profile"]["username"], "nasa")
        # 不应混入 Facebook 专属字段
        self.assertNotIn("fb_page_id", form)
        self.assertNotIn("fb_page_url", form)

    def test_form_drops_empty(self):
        form = influencer_service.ig_profile_to_form({"username": "natgeo"})
        self.assertEqual(form["display_name"], "natgeo")
        self.assertEqual(form["ig_username"], "natgeo")
        self.assertNotIn("website", form)


class FbFormHelpersRestoredTests(unittest.TestCase):
    """回归保护：合并 PR #15 时曾丢失这些函数，导致内联自动抓取弹窗存库崩溃。"""

    def test_normalize_group_user_url(self):
        self.assertEqual(
            influencer_service.normalize_fb_profile_url(
                "https://www.facebook.com/groups/123/user/456/"
            ),
            "https://www.facebook.com/profile.php?id=456",
        )

    def test_normalize_passthrough_non_fb(self):
        self.assertEqual(
            influencer_service.normalize_fb_profile_url("https://example.com/x"),
            "https://example.com/x",
        )

    def test_page_profile_to_form(self):
        form = influencer_service.page_profile_to_form(FB_PAGE_SAMPLE)
        self.assertEqual(form["display_name"], "Humans of New York")
        self.assertEqual(form["fb_page_id"], "10643211755")
        self.assertEqual(form["email"], "hi@example.com")
        self.assertNotIn("raw_profile", form)


# 取自 facebook-profile-scraper（apivault_labs 等）的精简样例
FB_PROFILE_SCRAPER_SAMPLE = {
    "inputUrl": "https://www.facebook.com/vanityluxejpn",
    "profileType": "profile",
    "username": "vanityluxejpn",
    "fullName": "Vanity Luxe Jpn",
    "bio": "正品二手设计师单品",
    "category": "Digital creator",
    "verified": False,
    "profileUrl": "https://www.facebook.com/vanityluxejpn",
    "avatarUrl": "https://example.com/avatar.jpg",
    "followerCount": 5505,
    "likeCount": 0,
    "websites": ["https://shop.example.com/"],
    "primaryWebsite": "https://shop.example.com/",
    "emails": ["hello@example.com"],
    "primaryEmail": "hello@example.com",
}


class FbProfileScraperFallbackTests(unittest.TestCase):
    """个人/创作者主页 facebook-profile-scraper 兜底的纯函数逻辑。"""

    def test_fb_profile_to_form(self):
        form = influencer_service.fb_profile_to_form(FB_PROFILE_SCRAPER_SAMPLE)
        self.assertEqual(form["display_name"], "Vanity Luxe Jpn")
        self.assertEqual(form["fb_page_title"], "Vanity Luxe Jpn")
        self.assertEqual(form["fb_page_url"], "https://www.facebook.com/vanityluxejpn")
        self.assertEqual(form["fb_followers"], 5505)
        self.assertEqual(form["bio"], "正品二手设计师单品")
        self.assertEqual(form["email"], "hello@example.com")
        self.assertEqual(form["website"], "https://shop.example.com/")
        self.assertEqual(form["fb_categories"], ["Digital creator"])

    def test_sparse_detection(self):
        # pages-scraper 抓 Profile 类账号：拿不到昵称(Unknown) + 没粉丝 → 稀疏
        sparse = {"display_name": "Unknown", "fb_page_url": "https://www.facebook.com/x"}
        self.assertTrue(influencer_service.fb_form_is_sparse(sparse))
        # 正常 Page：有昵称或粉丝 → 不稀疏
        rich = influencer_service.page_profile_to_form(FB_PAGE_SAMPLE)
        self.assertFalse(influencer_service.fb_form_is_sparse(rich))
        # 只要有粉丝数也算不稀疏
        self.assertFalse(
            influencer_service.fb_form_is_sparse(
                {"display_name": "Unknown", "fb_followers": 100}
            )
        )

    def test_merge_prefers_primary_then_fills_from_fallback(self):
        primary = {"display_name": "Unknown", "fb_page_url": "https://www.facebook.com/vanityluxejpn"}
        fallback = influencer_service.fb_profile_to_form(FB_PROFILE_SCRAPER_SAMPLE)
        merged = influencer_service.merge_fb_forms(primary, fallback)
        # display_name 为 Unknown → 用 fallback 的真实昵称
        self.assertEqual(merged["display_name"], "Vanity Luxe Jpn")
        # primary 非空字段优先保留
        self.assertEqual(merged["fb_page_url"], "https://www.facebook.com/vanityluxejpn")
        # fallback 补齐 primary 缺失的字段
        self.assertEqual(merged["fb_followers"], 5505)
        self.assertEqual(merged["email"], "hello@example.com")


if __name__ == "__main__":
    unittest.main()
