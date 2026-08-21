from bot.parlays import flair_icons


def test_get_flair_icon_url_returns_none_for_unknown_school():
    assert flair_icons.get_flair_icon_url("Rice University") is None


def test_get_flair_icon_url_covers_the_teams_with_dedicated_zingers():
    for school in ("Purdue", "Ohio State", "Indiana", "UCF", "Oklahoma State"):
        assert flair_icons.get_flair_icon_url(school) is not None


def test_flair_icon_urls_all_point_at_the_expected_cdn():
    for url in flair_icons.FLAIR_ICON_URLS.values():
        assert url.startswith("https://cdn.redditcfb.com/60x40/cfb/")


def test_flair_icon_urls_has_no_duplicate_schools():
    schools = list(flair_icons.FLAIR_ICON_URLS)
    assert len(schools) == len(set(schools))
