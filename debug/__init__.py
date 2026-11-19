import sys

from wafer.core.common.profile import PROFILE_ARG, TOOLS_PROFILE, profile_from_args

if sys.argv[:1] == ["-m"] and profile_from_args(sys.argv) != TOOLS_PROFILE:
    sys.exit(f"The debug tools run only with {PROFILE_ARG} {TOOLS_PROFILE}, so they never write to or prune the normal Wafer's data folder.")
