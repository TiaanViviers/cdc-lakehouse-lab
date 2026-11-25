"""Stage the approved linux/amd64 image for the offline source VM."""

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


REPOSITORY = "docker.io/library/postgres"
REGISTRY = "https://registry-1.docker.io/v2/library/postgres"
INDEX = "sha256:cd0e9518bda5f2ea667ff84d22795d089720c883f288e215d97ce57437e8ef37"
INDEX_TYPE = "application/vnd.oci.image.index.v1+json"
MANIFEST_TYPE = "application/vnd.oci.image.manifest.v1+json"


def stage(output):
    token_url = "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/postgres:pull"
    with urlopen(token_url, timeout=30) as response:
        token = json.load(response)["token"]

    with tempfile.TemporaryDirectory(dir=output.parent) as directory:
        layout = Path(directory)
        blobs = layout / "blobs" / "sha256"
        blobs.mkdir(parents=True)

        def fetch(kind, digest):
            match = re.fullmatch(r"sha256:([0-9a-f]{64})", digest)
            if not match:
                raise ValueError(f"Invalid SHA-256 digest: {digest}")
            hex_digest = match[1]
            path = blobs / hex_digest
            request = Request(f"{REGISTRY}/{kind}/{digest}", headers={
                "Accept": f"{INDEX_TYPE},{MANIFEST_TYPE}",
            })
            request.add_unredirected_header("Authorization", f"Bearer {token}")
            with urlopen(request, timeout=30) as response, path.open("xb") as file:
                shutil.copyfileobj(response, file)
            with path.open("rb") as file:
                if hashlib.file_digest(file, "sha256").hexdigest() != hex_digest:
                    raise ValueError(f"Registry content failed verification: {digest}")
            return path

        index = fetch("manifests", INDEX)
        platform = {"os": "linux", "architecture": "amd64"}
        descriptor = next(item for item in json.loads(index.read_bytes())["manifests"]
                          if item.get("platform") == platform)
        manifest = json.loads(fetch("manifests", descriptor["digest"]).read_bytes())
        digests = {item["digest"] for item in [manifest["config"], *manifest["layers"]]}
        with ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(lambda digest: fetch("blobs", digest), digests))

        # Preserve the registry index byte for byte. Docker's containerd store
        # loads the archive with only the blobs needed by the guest platform.
        ref = f"{REPOSITORY}@{INDEX}"
        (layout / "index.json").write_text(json.dumps({"schemaVersion": 2, "manifests": [{
            "mediaType": INDEX_TYPE, "size": index.stat().st_size, "digest": INDEX,
            "annotations": {"io.containerd.image.name": ref, "org.opencontainers.image.ref.name": ref},
        }]}), encoding="utf-8")
        (layout / "oci-layout").write_text('{"imageLayoutVersion":"1.0.0"}', encoding="utf-8")
        with tarfile.open(output, "x") as archive:
            for entry in ("index.json", "oci-layout", "blobs"):
                archive.add(layout / entry, arcname=entry)

    print(f"linux/amd64 index={INDEX} manifest={descriptor['digest']} config={manifest['config']['digest']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="new OCI archive outside version control")
    stage(parser.parse_args().output)
