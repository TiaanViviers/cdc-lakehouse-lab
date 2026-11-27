"""Extract link-time files only from the verified linux/amd64 consumer image."""

import json
from pathlib import Path
import re
import shutil
import sys
import tarfile

from scripts.cdc.consumer.image import MEMBER, blob_path, verify


def extract(image, build):
    verify(image)
    wanted = {
        "usr/lib/postgresql/18/lib/libduckdb.so": "libduckdb.so",
        "usr/lib/postgresql/18/bin/pg_config": "pg_config.real",
    }
    with tarfile.open(image) as archive:
        manifest = json.load(archive.extractfile(blob_path("sha256:" + MEMBER)))
        for descriptor in manifest["layers"]:
            with tarfile.open(fileobj=archive.extractfile(blob_path(descriptor["digest"])), mode="r|*") as layer:
                for member in layer:
                    if not member.isfile():
                        continue
                    name = wanted.get(member.name)
                    if re.fullmatch(r"usr/lib/x86_64-linux-gnu/libpq\.so\.5\.\d+", member.name):
                        name = "libpq.so.5"
                    if name:
                        with layer.extractfile(member) as source, (build / name).open("wb") as destination:
                            shutil.copyfileobj(source, destination)
    (build / "pg_config.real").chmod(0o755)
    for name in ("libduckdb.so", "libpq.so.5"):
        if not (build / name).is_file():
            raise ValueError(f"verified image is missing {name}")
    link = build / "libpq.so"
    if link.is_symlink() and link.readlink() == Path("libpq.so.5"):
        return
    link.symlink_to("libpq.so.5")


if __name__ == "__main__":
    extract(*map(Path, sys.argv[1:]))
