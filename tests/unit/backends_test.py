import pathlib

import pytest

from data.backends.s3 import S3Path, sync_local_to_remote, sync_remote_to_local


@pytest.fixture
def s3_bucket():
    return "dead-gecco-prod-features-raw"


def test_s3_sync(s3_bucket: str):
    pytest.skip("I currently don't have S3 permissions")
    sync_local_p = pathlib.Path(__file__).parent.parent / "data"
    old_local_files = set(sync_local_p.rglob("*"))
    remote_path = S3Path.from_path_str(bucket=s3_bucket, path="test")
    sync_local_to_remote(local=sync_local_p, remote=remote_path, pretty=True)
    for f in old_local_files:
        if f.is_file():
            f.unlink()  # Delete them all.
    (sync_local_p / "wrong").touch()  # Also create a bad file that should get deleted.
    sync_remote_to_local(remote=remote_path, local=sync_local_p, pretty=True)
    new_local_files = set(sync_local_p.rglob("*"))
    assert old_local_files == new_local_files

    # git checkout origin/master -- tests/data*
    # will undo any mistakes here and revert that directory.
