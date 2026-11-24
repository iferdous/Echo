from echo.cross_dataset import plan_cohort
from echo.datasets import Asset


def asset(source, suffix="", label="dog"):
    return Asset(
        f"esc50:{source}{suffix}",
        "esc50",
        "v1",
        f"{source}{suffix}.wav",
        "source",
        "freesound",
        source,
        label,
        sha256="a" * 64,
    )


def test_cohort_preserves_shared_rows_and_samples_controls_without_known_ids():
    esc = [
        asset("11", "-a"),
        asset("11", "-b"),
        asset("12"),
        asset("13"),
        asset("14", label="cat"),
    ]
    fsd = {
        "11": ("Bark",),
        "21": ("Bark",),
        "22": ("Bark",),
        "23": ("Cat",),
        "24": ("Other",),
    }
    spec = {
        "seed": 8,
        "class_queries_per_label": 1,
        "class_references_per_label": 1,
        "background_queries": 1,
        "background_references": 1,
        "class_map": {"dog": "Bark"},
    }
    plan = plan_cohort(esc, fsd, {"12"}, spec)
    refs, queries, coverage = plan
    assert plan == plan_cohort(
        list(reversed(esc)), dict(reversed(list(fsd.items()))), {"12"}, spec
    )
    assert [row.asset_id for row in queries if row.role == "shared_eval_id"] == [
        "esc50:11-a",
        "esc50:11-b",
    ]
    assert {row.source_id for row in queries if row.role != "shared_eval_id"} == {
        "13",
        "14",
    }
    assert 1 == sum(row.role == "shared_eval_id" for row in refs)
    assert 3 == len({row.source_id for row in refs}) == len(refs)
    assert coverage[0]["query_count"] == 1
    assert all(row.asset_id.startswith("reference-") for row in refs)
