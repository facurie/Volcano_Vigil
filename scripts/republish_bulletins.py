"""Re-render every bulletin stored in a database into its published folder (vigil.agent.render.publish), for
example after the bulletins became English only:

    python scripts/republish_bulletins.py --db data/replay/ep55/vigil.sqlite --out data/replay/ep55/bulletins
"""

from __future__ import annotations

import argparse
from contextlib import closing
from pathlib import Path

from vigil import db
from vigil.agent.bulletin import load_bulletin
from vigil.agent.render import publish
from vigil.settings import Settings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="the bulletins folder, inside the data dir")
    args = parser.parse_args(argv)
    data_dir = Settings.from_env().data_dir
    with closing(db.connect(args.db)) as conn:
        ids = [row[0] for row in conn.execute("SELECT id FROM bulletins ORDER BY id")]
        for bulletin_id in ids:
            print(publish(load_bulletin(conn, bulletin_id), data_dir, args.out))


if __name__ == "__main__":
    main()
