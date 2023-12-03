from data.backends.s3 import S3Path, sync_local_to_remote, sync_remote_to_local
from data.coledb.coledb import ColeDBInterface


def sync_to_remote(cole: ColeDBInterface, remote: S3Path):
    sync_local_to_remote(local=cole.cole_db_storage_path, remote=remote, pretty=True)


def sync_from_remote(cole: ColeDBInterface, remote: S3Path):
    sync_remote_to_local(remote=remote, local=cole.cole_db_storage_path, pretty=True)
