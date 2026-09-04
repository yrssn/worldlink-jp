from app.services.influencer_service import (
    CrossUserIndex,
    cross_user_match_for_form,
    normalize_fb_url,
)


def _index() -> CrossUserIndex:
    idx = CrossUserIndex()
    idx.fb_page_ids["100001"] = "cindy"
    idx.urls[normalize_fb_url("https://www.facebook.com/profile.php?id=100001")] = "cindy"
    idx.urls[normalize_fb_url("https://www.facebook.com/SomeBrand/")] = "cindy"
    idx.ig_handles["kol_a"] = "cindy"
    idx.urls[normalize_fb_url("https://instagram.com/kol_a")] = "cindy"
    return idx


def test_fb_profile_ids_are_distinct():
    idx = _index()
    assert idx.match("facebook", url="https://facebook.com/profile.php?id=100001") == "cindy"
    assert idx.match("facebook", url="https://facebook.com/profile.php?id=100002") is None


def test_fb_page_id_wins_over_url():
    idx = _index()
    assert idx.match("facebook", url="https://facebook.com/other.vanity", page_id="100001") == "cindy"
    # 有 page_id 时不看链接：链接相同但 id 不同 -> 不算重复
    assert idx.match("facebook", url="https://facebook.com/SomeBrand", page_id="999") is None


def test_ig_matches_by_username_or_url():
    idx = _index()
    assert idx.match("instagram", handle="@KOL_A", url="https://www.instagram.com/x/") == "cindy"
    assert idx.match("instagram", url="https://www.instagram.com/kol_a/") == "cindy"
    assert idx.match("instagram", handle="kol_b", url="https://instagram.com/kol_b") is None
    # IG 不走 FB 的 page_id 逻辑
    assert idx.match("instagram", handle="kol_b", page_id="100001") is None


def test_match_for_form():
    idx = _index()
    assert cross_user_match_for_form(idx, "facebook", {"fb_page_id": "100001", "fb_page_url": "x"}) == "cindy"
    assert cross_user_match_for_form(idx, "instagram", {"ig_username": "kol_a"}) == "cindy"
    assert cross_user_match_for_form(CrossUserIndex(), "instagram", {"ig_username": "kol_a"}) is None


def test_profile_php_without_id_never_matches():
    assert normalize_fb_url("https://www.facebook.com/profile.php") == ""
    assert normalize_fb_url("https://www.facebook.com/profile.php?id=100001") == "facebook.com/profile.php?id=100001"
    idx = _index()
    assert idx.match("facebook", url="https://facebook.com/profile.php") is None
