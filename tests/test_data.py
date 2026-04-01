from __future__ import annotations

from more_tweaks.data import CATEGORIES, CATEGORY_TWEAK_ORDER, TWEAKS, filter_tweaks

VALID_CONTROLS = {
    "boolean", "boolean-inverted", "number", "choice",
    "text", "text-list", "keybinding", "feature-toggle",
}
VALID_VALUE_TYPES = {"boolean", "string", "int", "uint32", "uint64", "double", "array"}
CATEGORY_IDS = {c.id for c in CATEGORIES}


class TestCategoryIntegrity:
    def test_no_duplicate_ids(self):
        ids = [c.id for c in CATEGORIES]
        assert len(ids) == len(set(ids))

    def test_required_fields(self):
        for cat in CATEGORIES:
            assert cat.id, f"Category missing id"
            assert cat.name, f"Category {cat.id} missing name"
            assert cat.icon_name, f"Category {cat.id} missing icon_name"


class TestTweakIntegrity:
    def test_no_duplicate_ids(self):
        ids = [t.id for t in TWEAKS]
        assert len(ids) == len(set(ids)), "Duplicate tweak IDs found"

    def test_required_fields(self):
        for t in TWEAKS:
            assert t.id, "Tweak missing id"
            assert t.name, f"Tweak {t.id} missing name"
            assert t.summary, f"Tweak {t.id} missing summary"
            assert t.description, f"Tweak {t.id} missing description"
            assert t.category, f"Tweak {t.id} missing category"
            assert t.schema, f"Tweak {t.id} missing schema"
            assert t.key, f"Tweak {t.id} missing key"
            assert t.value_type, f"Tweak {t.id} missing value_type"
            assert t.control, f"Tweak {t.id} missing control"

    def test_valid_categories(self):
        for t in TWEAKS:
            assert t.category in CATEGORY_IDS, (
                f"Tweak {t.id} references unknown category {t.category!r}"
            )

    def test_valid_control_types(self):
        for t in TWEAKS:
            assert t.control in VALID_CONTROLS, (
                f"Tweak {t.id} has invalid control {t.control!r}"
            )

    def test_valid_value_types(self):
        for t in TWEAKS:
            assert t.value_type in VALID_VALUE_TYPES, (
                f"Tweak {t.id} has invalid value_type {t.value_type!r}"
            )

    def test_number_tweaks_have_range(self):
        for t in TWEAKS:
            if t.control == "number":
                assert t.min_value is not None, f"Number tweak {t.id} missing min_value"
                assert t.max_value is not None, f"Number tweak {t.id} missing max_value"

    def test_choice_tweaks_have_choices(self):
        for t in TWEAKS:
            if t.control in {"choice", "feature-toggle"}:
                assert len(t.choices) > 0, (
                    f"Tweak {t.id} with control={t.control!r} has no choices"
                )

    def test_category_tweak_order_references_valid_ids(self):
        tweak_ids = {t.id for t in TWEAKS}
        for cat_id, order in CATEGORY_TWEAK_ORDER.items():
            assert cat_id in CATEGORY_IDS, (
                f"CATEGORY_TWEAK_ORDER references unknown category {cat_id!r}"
            )
            for tweak_id in order:
                assert tweak_id in tweak_ids, (
                    f"CATEGORY_TWEAK_ORDER[{cat_id!r}] references unknown tweak {tweak_id!r}"
                )


class TestFilterTweaks:
    def test_empty_query_returns_all(self):
        results = filter_tweaks("", None)
        assert len(results) == len(TWEAKS)

    def test_filter_by_category(self):
        from more_tweaks.data import CHILD_CATEGORIES
        for cat in CATEGORIES:
            if cat.id == "animations":
                continue
            results = filter_tweaks("", cat.id)
            allowed = {cat.id} | CHILD_CATEGORIES.get(cat.id, set())
            for t in results:
                assert t.category in allowed, (
                    f"filter_tweaks for {cat.id} returned tweak {t.id} from {t.category}"
                )

    def test_search_returns_results(self):
        results = filter_tweaks("animation", None)
        assert len(results) > 0

    def test_search_no_results(self):
        results = filter_tweaks("zzzznonexistentzzzz", None)
        assert len(results) == 0

    def test_search_matches_tags(self):
        results = filter_tweaks("performance", None)
        assert any("performance" in t.tags for t in results)
