import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import pr_size


def test_counts_only_src_paths():
    text = "10\t0\tsrc/refdes/cli.py\n4\t2\tdocs/cli-reference.md\n1\t1\tREADME.md\n"
    assert pr_size.count_src_additions(text) == 10


def test_rename_full_path_form_uses_new_path():
    text = "5\t5\told/name.py => new/name.py\n"
    assert pr_size.count_src_additions(text) == 0
    text = "5\t5\tsrc/a.py => src/b.py\n"
    assert pr_size.count_src_additions(text) == 5
    text = "5\t5\tsrc/{a.py => b.py}\n"
    assert pr_size.count_src_additions(text) == 5


def test_rename_brace_form_with_shared_prefix_and_suffix():
    text = "7\t0\tsrc/refdes/{build.py => navis_build.py}\n"
    assert pr_size.count_src_additions(text) == 7
    text = "7\t0\ttests/{a_test.py => b_test.py}\n"
    assert pr_size.count_src_additions(text) == 0


def test_rename_out_of_and_into_src():
    into = "9\t0\ttools/x.py => src/refdes/x.py\n"
    assert pr_size.count_src_additions(into) == 9
    out = "9\t0\tsrc/refdes/x.py => tools/x.py\n"
    assert pr_size.count_src_additions(out) == 0


def test_plain_name_with_space_arrow_is_not_split_on_dots():
    text = "3\t0\told/a.py => new/b.py\n"
    assert pr_size.new_path_of(text.split("\t")[2]) == "new/b.py"


def test_deleted_src_file_counts_zero():
    text = "0\t12\tsrc/refdes/gone.py\n"
    assert pr_size.count_src_additions(text) == 0


def test_binary_dash_counts_zero():
    text = "-\t-\tsrc/refdes/blob.bin\n"
    assert pr_size.count_src_additions(text) == 0


def test_empty_diff_counts_zero():
    assert pr_size.count_src_additions("") == 0
    assert pr_size.count_src_additions("\n") == 0


def test_non_src_directories_are_ignored():
    text = (
        "100\t0\ttests/test_a.py\n50\t0\tchangelog.d/x.added.md\n"
        "30\t0\tin-prog-logs/log.md\n20\t0\ttools/tool.py\n"
        "40\t0\t.github/workflows/ci.yml\ndocs/a.md\n"
    )
    assert pr_size.count_src_additions(text) == 0


def test_budged_paths_are_not_src():
    assert pr_size.count_src_additions("50\t0\tsrcish/thing.py\n") == 0
    assert pr_size.count_src_additions("50\t0\tsrc\n") == 0


def test_multiline_sum():
    text = "100\t0\tsrc/a.py\n200\t0\tsrc/b.py\n60\t0\ttests/t.py\n51\t0\tsrc/c.py\n"
    assert pr_size.count_src_additions(text) == 351


def test_exactly_budget_passes_over_budget_fails():
    assert pr_size.over_budget(pr_size.BUDGET, 401, False) is False
    assert pr_size.over_budget(pr_size.BUDGET + 1, 401, False) is True


def test_grandfathered_prs_never_fail():
    over = pr_size.BUDGET + 1000
    assert pr_size.over_budget(over, pr_size.FIRST_ENFORCED_PR - 1, False) is False
    assert pr_size.over_budget(over, 1, False) is False
    assert pr_size.over_budget(over, pr_size.FIRST_ENFORCED_PR, False) is True
    assert pr_size.over_budget(over, pr_size.FIRST_ENFORCED_PR + 1, False) is True


def test_label_waiver():
    assert pr_size.is_exempt("size-exempt") is True
    assert pr_size.is_exempt("bugfix, size-exempt , docs") is True
    assert pr_size.is_exempt("bugfix,docs") is False
    assert pr_size.is_exempt("") is False
    assert pr_size.is_exempt("not-size-exempt") is False
    assert pr_size.over_budget(pr_size.BUDGET + 100, 500, True) is False


def test_no_pr_number_fails_closed_over_budget():
    assert pr_size.over_budget(pr_size.BUDGET + 1, None, False) is True
    assert pr_size.over_budget(pr_size.BUDGET, None, False) is False
