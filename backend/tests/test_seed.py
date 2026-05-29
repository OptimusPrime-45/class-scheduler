"""Determinism + structural-invariant tests for the seed dataset (no DB needed)."""

from __future__ import annotations

import json

from seed import CURRICULUM, build_seed_data


def test_build_seed_data_is_deterministic():
    a = build_seed_data()
    b = build_seed_data()
    assert a == b
    # Stronger: identical canonical serialisation (catches ordering/type drift).
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_dataset_counts_match_readme():
    d = build_seed_data()
    assert len(d["subjects"]) == 8
    assert len(d["batches"]) == 6
    assert len(d["teachers"]) == 20
    assert len(d["batch_subjects"]) == 6 * len(CURRICULUM)
    assert len(d["batch_slots"]) == 6 * 6 * 4  # 6 batches x Mon–Sat x 4 periods


def test_every_batch_subject_owner_is_qualified():
    """Validator invariant (c): a (batch,subject) owner must teach that subject."""
    d = build_seed_data()
    quals = {t["full_name"]: set(t["qualifications"]) for t in d["teachers"]}
    for bs in d["batch_subjects"]:
        assert bs["subject_code"] in quals[bs["owner_teacher_name"]]


def test_every_curriculum_subject_has_a_qualified_teacher():
    """Feasibility precondition: no demand is impossible to satisfy by qualification."""
    d = build_seed_data()
    all_quals = {code for t in d["teachers"] for code in t["qualifications"]}
    for code, _target in CURRICULUM:
        assert code in all_quals


def test_grades_within_supported_range():
    d = build_seed_data()
    for b in d["batches"]:
        assert 5 <= b["grade"] <= 10


def test_single_global_settings_row():
    d = build_seed_data()
    assert d["settings"]["scope"] == "GLOBAL"
    assert d["settings"]["timezone"] == "Asia/Kolkata"
