from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from urllib.request import Request


script = Path(__file__).resolve().parents[2] / "scripts/source/stage-image.py"
spec = importlib.util.spec_from_file_location("stage_image", script)
stage_image = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage_image)


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def image_index(*descriptors):
    return (json.dumps({"schemaVersion": 2, "manifests": descriptors}, indent=2) + "\n").encode()


class SourceStageImageTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.output = Path(directory.name) / "source.tar"
        self.config = b'{"architecture":"amd64","os":"linux"}'
        self.layers = [b"synthetic layer one", b"synthetic layer two"]
        self.manifest = json.dumps({
            "config": {"digest": digest(self.config)},
            "layers": [{"digest": digest(layer)} for layer in self.layers],
        }).encode()
        self.arm = {
            "platform": {"os": "linux", "architecture": "arm64"},
            "digest": digest(b"unused arm64 manifest"),
        }
        self.amd = {
            "platform": {"os": "linux", "architecture": "amd64"},
            "digest": digest(self.manifest),
        }
        self.index = image_index(self.arm, self.amd)
        self.blobs = {
            f"blobs/{digest(data)}": data for data in [self.config, *self.layers]
        }
        self.content = {
            f"manifests/{digest(self.index)}": self.index,
            f"manifests/{digest(self.manifest)}": self.manifest,
            **self.blobs,
        }

    def stage(self, index, content):
        def registry_response(request, *, timeout):
            if isinstance(request, str):
                self.assertTrue(request.startswith("https://auth.docker.io/token?"))
                return io.BytesIO(b'{"token":"fixture"}')
            self.assertIsInstance(request, Request)
            prefix = f"{stage_image.REGISTRY}/"
            self.assertTrue(request.full_url.startswith(prefix))
            return io.BytesIO(content[request.full_url.removeprefix(prefix)])

        with patch.object(stage_image, "INDEX", digest(index)), patch.object(
                stage_image, "urlopen", side_effect=registry_response), redirect_stdout(io.StringIO()):
            stage_image.stage(self.output)

    def test_digest_mismatch_rejects_corrupt_registry_content(self):
        for endpoint in self.content:
            with self.subTest(endpoint=endpoint):
                bad_content = {**self.content, endpoint: b"tampered"}
                with self.assertRaisesRegex(ValueError, f"failed verification: {endpoint.split('/')[1]}"):
                    self.stage(self.index, bad_content)
                self.assertEqual(list(self.output.parent.iterdir()), [])

    def test_missing_linux_amd64_manifest_rejects_index(self):
        index = image_index(self.arm)
        with self.assertRaisesRegex(ValueError, "no linux/amd64 manifest"):
            self.stage(index, {f"manifests/{digest(index)}": index})
        self.assertEqual(list(self.output.parent.iterdir()), [])

    def test_archive_preserves_index_and_contains_only_selected_payload(self):
        self.stage(self.index, self.content)
        with tarfile.open(self.output) as archive:
            files = {member.name: archive.extractfile(member).read()
                     for member in archive if member.isfile()}

        self.assertEqual(json.loads(files.pop("oci-layout")), {"imageLayoutVersion": "1.0.0"})
        ref = f"docker.io/library/postgres@{digest(self.index)}"
        self.assertEqual(json.loads(files.pop("index.json")), {
            "schemaVersion": 2,
            "manifests": [{
                "mediaType": "application/vnd.oci.image.index.v1+json",
                "size": len(self.index),
                "digest": digest(self.index),
                "annotations": {
                    "io.containerd.image.name": ref,
                    "org.opencontainers.image.ref.name": ref,
                },
            }],
        })
        self.assertEqual(files, {
            f"blobs/sha256/{digest(data).removeprefix('sha256:')}": data
            for data in [self.index, self.manifest, self.config, *self.layers]
        })
