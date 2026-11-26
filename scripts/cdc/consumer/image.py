"""Stage or verify the approved linux/amd64 consumer OCI archive."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import shutil
import tarfile
import tempfile
from urllib.request import Request, urlopen


REPOSITORY = "pgducklake/pipe-ci-builds"
INDEX = "091236d2acecfec1216817aff6e43dc4c036159cebe44a19c73c95c1fe9be348"
MEMBER = "de0a9036fd11a75eaff23508209c2cea675d081aecea51f60cdca78c0802a5a6"
CONFIG = "a0452c3a54190ba6eeaf94dd3e434f97fd3862944c73b3f681f85eb8e3b2f56e"
REF = f"docker.io/{REPOSITORY}@sha256:{INDEX}"
INDEX_TYPE = "application/vnd.oci.image.index.v1+json"
MANIFEST_TYPE = "application/vnd.oci.image.manifest.v1+json"
PLATFORM = {"architecture": "amd64", "os": "linux"}


def blob_path(digest):
    if not re.fullmatch("sha256:[0-9a-f]{64}", digest):
        raise ValueError("unexpected digest format")
    return f"blobs/sha256/{digest[7:]}"


def verify(path):
    with tarfile.open(path, "r:") as archive:
        def checked_blob(digest, as_json=False):
            with archive.extractfile(blob_path(digest)) as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != digest[7:]:
                    raise ValueError("OCI blob digest mismatch")
            if as_json:
                return json.loads(archive.extractfile(blob_path(digest)).read())

        refs = json.load(archive.extractfile("index.json"))["manifests"]
        if len(refs) != 1 or refs[0]["digest"] != f"sha256:{INDEX}":
            raise ValueError("unexpected archive index")
        if refs[0]["annotations"]["io.containerd.image.name"] != REF:
            raise ValueError("unexpected archive reference")
        index = checked_blob(f"sha256:{INDEX}", as_json=True)
        members = [row["digest"] for row in index["manifests"] if row.get("platform") == PLATFORM]
        if members != [f"sha256:{MEMBER}"]:
            raise ValueError("unexpected linux/amd64 member")
        manifest = checked_blob(members[0], as_json=True)
        if manifest["config"]["digest"] != f"sha256:{CONFIG}":
            raise ValueError("unexpected image config digest")
        config = checked_blob(f"sha256:{CONFIG}", as_json=True)
        if {key: config[key] for key in PLATFORM} != PLATFORM:
            raise ValueError("unexpected config platform")
        for layer in manifest["layers"]:
            checked_blob(layer["digest"])
    print(f"linux/amd64 index=sha256:{INDEX} manifest=sha256:{MEMBER} config=sha256:{CONFIG}")


def stage(path):
    if path.exists():
        raise FileExistsError(path)
    token_url = f"https://auth.docker.io/token?service=registry.docker.io&scope=repository:{REPOSITORY}:pull"
    with urlopen(token_url, timeout=30) as response:
        token = json.load(response)["token"]
    with tempfile.TemporaryDirectory(dir=path.parent) as scratch:
        layout = Path(scratch)
        (layout / "blobs/sha256").mkdir(parents=True)

        def fetch(kind, digest):
            target = layout / blob_path(digest)
            request = Request(f"https://registry-1.docker.io/v2/{REPOSITORY}/{kind}/{digest}",
                              headers={"Accept": f"{INDEX_TYPE},{MANIFEST_TYPE}"})
            request.add_unredirected_header("Authorization", f"Bearer {token}")
            with urlopen(request, timeout=30) as response, target.open("xb") as out:
                shutil.copyfileobj(response, out)
            return target

        index = fetch("manifests", f"sha256:{INDEX}")
        manifest = json.loads(fetch("manifests", f"sha256:{MEMBER}").read_text())
        digests = {f"sha256:{CONFIG}", *(layer["digest"] for layer in manifest["layers"])}
        with ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(lambda digest: fetch("blobs", digest), digests))
        (layout / "oci-layout").write_text('{"imageLayoutVersion":"1.0.0"}')
        (layout / "index.json").write_text(json.dumps({"schemaVersion": 2, "manifests": [{
            "mediaType": INDEX_TYPE, "size": index.stat().st_size, "digest": f"sha256:{INDEX}",
            "annotations": {"io.containerd.image.name": REF, "org.opencontainers.image.ref.name": REF},
        }]}))
        temporary = layout / "image.tar"
        with tarfile.open(temporary, "x") as archive:
            for entry in ("oci-layout", "index.json", "blobs"):
                archive.add(layout / entry, arcname=entry)
        verify(temporary)
        path.hardlink_to(temporary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("stage", "verify"))
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    (stage if args.action == "stage" else verify)(args.archive)
