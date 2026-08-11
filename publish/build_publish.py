#!/usr/bin/env python3
"""
Build a clean ClawHub publish bundle from the Book Learning Tutor repo.

Portable: derives the repo root and the publish folder from THIS script's own
location, so it works no matter where the repo is cloned (no hardcoded paths).

What it does
------------
Reads `git ls-files -z` from the source repo (raw UTF-8, no shell quoting), so
it always mirrors exactly what "Import from GitHub" would pull -- automatically
excludes .gitignore'd dirs like venv_slim/, 书库/, 参考/, data/, _backup_/, etc.
Then copies every tracked file into the publish folder EXCEPT a small blocklist
of repo-only artifacts that must not ship inside an installed skill:

  .github/   CI workflows (not part of the installed skill)
  tests/     dev-only tests + fixtures
  LICENSE    ClawHub forces MIT-0 and rejects a bundled LICENSE
  .gitignore repo-internal; irrelevant inside an installed skill
  publish/   this build toolchain itself (must not ship inside the skill)

Run whenever you bump the repo and want to re-publish:
  python publish/build_publish.py
then publish the generated "<repo> (publish)" sibling folder.

NOTE: the repo's safe-delete hook blocks agent-side deletion, so this script
overwrites in place instead of wiping. If a file is later REMOVED from tracking
its stale copy may linger in the publish folder -- delete it manually for a reset.
"""
import subprocess
import os
import shutil
import pathlib

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent      # .../publish
REPO = SCRIPT_DIR.parent                                  # .../Book Learning Tutor
DST = REPO.with_name(REPO.name + " (publish)")            # .../Book Learning Tutor (publish)

# Repo-only artifacts that must NOT be in the installed skill bundle.
EXCLUDE_TOP = {".github", "tests", "LICENSE", ".gitignore", ".git", "publish"}


def main() -> None:
    DST.mkdir(parents=True, exist_ok=True)

    # -z => NUL-separated raw bytes (UTF-8 on this system); avoids git's
    # octal/quote escaping of non-ASCII paths that breaks plain ls-files.
    out = subprocess.check_output(["git", "-C", str(REPO), "ls-files", "-z"])
    files = [f.decode("utf-8") for f in out.split(b"\0") if f.strip()]

    copied = skipped = 0
    for rel in files:
        if rel.split("/", 1)[0] in EXCLUDE_TOP:
            skipped += 1
            continue
        s = REPO / rel
        d = DST / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s, d)
        copied += 1

    print(f"Publish bundle built at: {DST}")
    print(f"  repo root      : {REPO}")
    print(f"  tracked files  : {len(files)}")
    print(f"  bundled        : {copied}")
    print(f"  excluded       : {skipped}  ({', '.join(sorted(EXCLUDE_TOP))})")


if __name__ == "__main__":
    main()
