"""csvdiff: compare two docs-index CSVs by their `path` column (stdlib only).

usage: python3 csvdiff.py OLD.csv NEW.csv [--limit N]
Prints counts and the first N added / removed / changed rows (path + changed columns). Exit 0 when identical, 1 when different.
"""
import csv
import sys


def load(path):
    rows = {}
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                rows[r.get("path", "")] = r
    except OSError:
        return None
    return rows


def main(argv):
    limit = 12
    args = [a for a in argv[1:]]
    if "--limit" in args:
        i = args.index("--limit")
        limit = int(args[i + 1])
        del args[i:i + 2]
    if len(args) != 2:
        print("usage: csvdiff.py OLD.csv NEW.csv [--limit N]", file=sys.stderr)
        return 2
    old, new = load(args[0]), load(args[1])
    if new is None:
        print("cannot read %s" % args[1], file=sys.stderr)
        return 2
    if old is None:
        print("old file absent: %d row(s) would be created" % len(new))
        return 1
    added = [p for p in new if p not in old]
    removed = [p for p in old if p not in new]
    changed = []
    for p in new:
        if p in old:
            cols = [c for c in new[p] if new[p].get(c) != old[p].get(c)]
            if cols:
                changed.append((p, cols))
    print("rows: %d -> %d; added %d, removed %d, changed %d" % (len(old), len(new), len(added), len(removed), len(changed)))
    for p in added[:limit]:
        print("  + %s" % p)
    for p in removed[:limit]:
        print("  - %s" % p)
    for p, cols in changed[:limit]:
        print("  ~ %s (%s)" % (p, ", ".join(cols)))
    more = max(0, len(added) - limit) + max(0, len(removed) - limit) + max(0, len(changed) - limit)
    if more:
        print("  ... and %d more" % more)
    return 1 if (added or removed or changed) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
