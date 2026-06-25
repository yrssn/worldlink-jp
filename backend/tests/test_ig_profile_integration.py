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


if __name__ == "__main__":
    unittest.main()
