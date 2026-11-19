import pytest

ROLE_ARGS = [
    [],
    ["--tray"],
    ["--viewer"],
    ["--webui"],
    ["--indexer", "sample"],
    ["--collector", "sample", "--plugin", "color"],
    ["--parser", "sample", "--plugin", "exif"],
]


@pytest.mark.parametrize("role_args", ROLE_ARGS, ids=lambda args: " ".join(args) or "root")
@pytest.mark.parametrize("profile_first", [True, False], ids=["profile-first", "profile-last"])
def test_parser_accepts_the_profile_with_every_role(role_args, profile_first):
    from main import build_parser

    profile = ["--profile", "debug-x"]
    argv = profile + role_args if profile_first else role_args + profile
    args = build_parser().parse_args(argv)

    assert args.profile == "debug-x"


def test_parser_leaves_the_profile_unset_without_the_option():
    from main import build_parser

    assert build_parser().parse_args(["--tray"]).profile is None


def test_parser_rejects_a_non_debug_profile(capsys):
    from main import build_parser

    with pytest.raises(SystemExit):
        build_parser().parse_args(["--profile", "release", "--tray"])
    assert "--profile" in capsys.readouterr().err
