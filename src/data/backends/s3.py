import base64
import hashlib
import pathlib
from dataclasses import dataclass
from multiprocessing.pool import ThreadPool

import boto3
import botocore.exceptions
import tqdm.autonotebook as tqdm

s3_resource = boto3.resource("s3")
s3_client = boto3.client("s3")


@dataclass(frozen=True)
class S3Path:
    bucket: str
    path_components: tuple[str, ...]

    @staticmethod
    def from_path_str(bucket: str, path: str) -> "S3Path":
        return S3Path(bucket=bucket, path_components=tuple(path.split("/")))

    @property
    def path(self):
        return "/".join(self.path_components)

    def __post_init__(self):
        if self.path[-1] == "/":
            raise ValueError('S3Paths must not end in "/"!')
        if any(not p for p in self.path_components):
            raise ValueError("No empty/falsey path components!")
        if any("/" in p for p in self.path_components):
            raise ValueError("/ cannot appear in any path components!")

    def checksum_sha256(self):
        return s3_client.head_object(
            Bucket=self.bucket, Key=self.path, ChecksumMode="ENABLED"
        ).get("ChecksumSHA256")

    @property
    def s3_object(self):
        return s3_resource.Object(bucket_name=self.bucket, key=self.path)

    @property
    def s3_summary(self):
        return s3_resource.ObjectSummary(bucket_name=self.bucket, key=self.path)

    def children(self, recursive: bool = False):
        req_kwargs = {"Bucket": self.bucket, "Prefix": self.path}
        if not recursive:
            req_kwargs["Delimiter"] = "/"
        while True:
            resp = s3_client.list_objects_v2(**req_kwargs)
            for obj in resp.get("Contents", []):
                yield S3Path.from_path_str(bucket=self.bucket, path=obj.get("Key"))
            if not resp.get("IsTruncated"):
                return
            req_kwargs["ContinuationToken"] = resp.get("NextContinuationToken")

    def exists(self) -> bool:
        try:
            self.s3_object.load()
        except botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
        return True


def sync_local_to_remote_file(local: pathlib.Path, remote: S3Path):
    local_b = local.read_bytes()
    local_checksum = (
        base64.encodebytes(hashlib.sha256(local_b).digest()).decode().strip()
    )
    if remote.exists():
        remote_checksum = remote.checksum_sha256()
        if local_checksum == remote_checksum:
            return  # No need to upload.
    s3_client.put_object(
        Bucket=remote.bucket,
        Key=remote.path,
        ChecksumAlgorithm="SHA256",
        ChecksumSHA256=local_checksum,
        Body=local_b,
    )


def sync_local_to_remote(local: pathlib.Path, remote: S3Path, pretty: bool = False):
    if local.is_file():
        sync_local_to_remote_file(local=local, remote=remote)
    elif local.is_dir():
        local_files = [f for f in local.rglob("*") if f.is_file()]
        # Sort from biggest to smallest.
        local_files.sort(reverse=True, key=lambda f: f.stat().st_size)
        # TODO: Upload in parallel.
        already_remote = remote.children(recursive=True)
        local_and_remote_paths = [
            (
                f,
                S3Path.from_path_str(
                    bucket=remote.bucket,
                    path=f"{remote.path}/{f.relative_to(local).as_posix()}",
                ),
            )
            for f in local_files
        ]
        wanted_remote_paths = (p for _, p in local_and_remote_paths)
        to_delete = set(already_remote).difference(wanted_remote_paths)
        with ThreadPool() as p:
            local_files_iter = p.imap_unordered(
                iterable=local_and_remote_paths,
                func=lambda t: sync_local_to_remote_file(
                    local=t[0],
                    remote=t[1],
                ),
            )
            to_delete_iter = to_delete
            if pretty:
                local_files_iter = tqdm.tqdm(
                    local_files_iter,
                    desc="Sync local to remote files",
                    total=len(local_and_remote_paths),
                )
                to_delete_iter = tqdm.tqdm(
                    to_delete_iter,
                    desc="Deleting remote files not present on local.",
                    total=len(to_delete),
                )
            list(local_files_iter)  # Iterate through it.
            for f in to_delete_iter:
                f.s3_object.delete()
    else:
        raise ValueError(f"Not a valid file type: {local}")


def sync_remote_to_local_file(remote: S3Path, local: pathlib.Path):
    if local.exists():
        local_checksum = (
            base64.encodebytes(hashlib.sha256(local.read_bytes()).digest())
            .decode()
            .strip()
        )
        remote_checksum = remote.checksum_sha256()
        if local_checksum == remote_checksum:
            return  # No need to upload.
    remote.s3_object.download_file(local.absolute().as_posix())


def sync_remote_to_local(remote: S3Path, local: pathlib.Path, pretty: bool = False):
    if remote.exists():
        sync_remote_to_local_file(remote=remote, local=local)
        return
    remote_and_local_paths = [
        (f.path, local / f.path.removeprefix(remote.path + "/"))
        for f in remote.children(recursive=True)
    ]
    wanted_local_paths = (lpath for _, lpath in remote_and_local_paths)
    to_delete = set(local.rglob("*")).difference(wanted_local_paths)
    with ThreadPool() as p:
        remote_files_iter = p.imap_unordered(
            iterable=remote_and_local_paths,
            func=lambda t: sync_remote_to_local_file(
                remote=S3Path.from_path_str(bucket=remote.bucket, path=t[0]),
                local=t[1],
            ),
        )

        to_delete_iter = to_delete
        if pretty:
            remote_files_iter = tqdm.tqdm(
                remote_files_iter,
                desc="Sync remote to local files",
                total=len(remote_and_local_paths),
            )
            to_delete_iter = tqdm.tqdm(
                to_delete_iter, desc="Deleting local files not present on remote."
            )

        list(remote_files_iter)  # Iterate through it.

        for f in to_delete_iter:
            if f.is_file():
                f.unlink()
