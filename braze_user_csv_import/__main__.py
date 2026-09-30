"""Run one import step without invoking Lambda.

Examples
--------
python -m braze_user_csv_import csv tests/fixtures/sample_users.csv
python -m braze_user_csv_import csv tests/fixtures/sample_users.csv --type-cast active_flag=boolean
python -m braze_user_csv_import braze payload.json
python -m braze_user_csv_import s3 my-bucket uploads/users.csv
"""

import sys

if __package__:
    from .braze_client import main as braze_main
    from .csv_processor import main as csv_main
    from .s3_handler import main as s3_main
else:
    from braze_client import main as braze_main
    from csv_processor import main as csv_main
    from s3_handler import main as s3_main


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print(__doc__)
        return 0
    command, rest = args[0], args[1:]
    commands = {
        "csv": csv_main,
        "braze": braze_main,
        "s3": s3_main,
    }
    if command not in commands:
        print(__doc__)
        print(f"Unknown command: {command}")
        return 2
    return commands[command](rest)


if __name__ == "__main__":
    raise SystemExit(main())
