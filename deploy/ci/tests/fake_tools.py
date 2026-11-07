#!/usr/bin/env python3
"""Fake docker / git / cosign for the deploy CI script tests (one file,
dispatching on the name it is called as). State: $FAKE_DIR/registry.json
({"tags": {"img:prod": digest}, "configs": {"img@digest": {labels}}});
every call is appended to $FAKE_DIR/calls.log.

docker buildx imagetools inspect REF --format '{{json .Manifest}}' | '{{json .Image}}'
docker buildx imagetools create --tag IMG:TAG IMG@DIGEST
git ls-remote URL refs/heads/main  → $FAKE_HEAD
cosign sign|verify …               → fails when $FAKE_COSIGN_FAIL names the verb
"""

import json
import os
import sys
from pathlib import Path

d = Path(os.environ["FAKE_DIR"])
tool = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(d / "calls.log", "a") as f:
    f.write(" ".join([tool, *args]) + "\n")
reg_path = d / "registry.json"
reg = (
    json.loads(reg_path.read_text())
    if reg_path.exists()
    else {"tags": {}, "configs": {}}
)


def resolve(ref):
    if "@" in ref:
        return ref.split("@", 1)[1] if ref in reg["configs"] else None
    return reg["tags"].get(ref)


if tool == "git":
    if args[:1] == ["ls-remote"]:
        head = os.environ.get("FAKE_HEAD", "")
        if head:
            print(f"{head}\trefs/heads/main")
        sys.exit(0)
    sys.exit(1)

if tool == "cosign":
    if args and args[0] == os.environ.get("FAKE_COSIGN_FAIL"):
        sys.exit(1)
    sys.exit(0)

if tool == "docker" and args[:2] == ["buildx", "imagetools"]:
    if args[2] == "inspect":
        ref, fmt = args[3], args[args.index("--format") + 1]
        digest = resolve(ref)
        if digest is None:
            print(f"ERROR: {ref}: not found", file=sys.stderr)
            sys.exit(1)
        if ".Manifest" in fmt:
            print(
                json.dumps(
                    {
                        "mediaType": "application/vnd.oci.image.index.v1+json",
                        "digest": digest,
                    }
                )
            )
        else:
            image = (
                ref.split("@")[0].split(":")[0] if "@" in ref else ref.rsplit(":", 1)[0]
            )
            labels = reg["configs"].get(f"{image}@{digest}")
            print(json.dumps({"config": {"Labels": labels}}))
        sys.exit(0)
    if args[2] == "create":
        tag, src = args[args.index("--tag") + 1], args[-1]
        if os.environ.get("FAKE_RETAG") == "wrong":
            reg["tags"][tag] = "sha256:" + "f" * 64
        else:
            reg["tags"][tag] = src.split("@", 1)[1]
        reg_path.write_text(json.dumps(reg))
        sys.exit(0)
sys.exit(2)
