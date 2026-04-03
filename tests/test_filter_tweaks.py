from __future__ import annotations

from more_tweaks.data import CATEGORIES, CHILD_CATEGORIES, TWEAKS, filter_tweaks


class TestFilterBasics:
    def test_empty_query_all_categories(self):
        results = filter_tweaks("", None)
        assert len(results) > 0
        # Should return all non-virtual-category tweaks
        assert len(results) <= len(TWEAKS)

    def test_category_filter(self):
        results = filter_tweaks("", "desktop")
        assert len(results) > 0
        for tweak in results:
            assert tweak.category == "desktop" or tweak.category in CHILD_CATEGORIES.get("desktop", set())

    def test_nonexistent_category(self):
        results = filter_tweaks("", "does-not-exist-xyz")
        assert results == []

    def test_search_returns_results(self):
        results = filter_tweaks("font", None)
        assert len(results) > 0

    def test_search_no_results(self):
        results = filter_tweaks("xyzzyplugh_nonexistent_query_99", None)
        assert results == []


class TestSearchMatching:
    def test_search_case_insensitive(self):
        lower = filter_tweaks("font", None)
        upper = filter_tweaks("FONT", None)
        mixed = filter_tweaks("Font", None)
        assert len(lower) == len(upper) == len(mixed)
        assert {t.id for t in lower} == {t.id for t in upper}

    def test_search_matches_schema(self):
        results = filter_tweaks("org.gnome.desktop.interface", None)
        assert len(results) > 0
        assert any("org.gnome.desktop.interface" in t.schema for t in results)

    def test_search_matches_key(self):
        results = filter_tweaks("enable-animations", None)
        assert len(results) > 0
        assert any("enable-animations" in t.key for t in results)

    def test_search_matches_tags(self):
        # Find a tweak that has tags and search for one
        tagged = [t for t in TWEAKS if t.tags]
        if tagged:
            tag = tagged[0].tags[0]
            results = filter_tweaks(tag, None)
            assert len(results) > 0

    def test_search_special_characters(self):
        # Should not crash on special regex characters
        for query in ["()", "[]", ".*", "\\", "+", "?", "{}", "|", "^$"]:
            results = filter_tweaks(query, None)
            assert isinstance(results, list)


class TestCategoryHierarchy:
    def test_child_category_included(self):
        # If "apps" has children, filtering by "apps" should include child tweaks
        if "apps" in CHILD_CATEGORIES and CHILD_CATEGORIES["apps"]:
            child_id = next(iter(CHILD_CATEGORIES["apps"]))
            child_tweaks = filter_tweaks("", child_id)
            parent_tweaks = filter_tweaks("", "apps")
            if child_tweaks:
                child_ids = {t.id for t in child_tweaks}
                parent_ids = {t.id for t in parent_tweaks}
                # Parent should include child category tweaks
                assert child_ids.issubset(parent_ids), (
                    "Parent category should include child category tweaks"
                )


class TestResultConsistency:
    def test_results_sorted_consistently(self):
        results1 = filter_tweaks("animation", None)
        results2 = filter_tweaks("animation", None)
        assert [t.id for t in results1] == [t.id for t in results2]

    def test_category_filter_with_query(self):
        all_results = filter_tweaks("dark", None)
        cat_results = filter_tweaks("dark", "themes")
        # Category-filtered results should be a subset
        cat_ids = {t.id for t in cat_results}
        all_ids = {t.id for t in all_results}
        assert cat_ids.issubset(all_ids)
