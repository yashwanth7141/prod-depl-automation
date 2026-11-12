
import getpass
import json
import os
import posixpath
import stat
from pathlib import Path

import paramiko


def create_remote_connection(host, username, password, port=22):
    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())

    ssh.connect(
        hostname=host,
        port=port,
        username=username,
        password=password,
        timeout=30,
        banner_timeout=30,
        auth_timeout=30,
    )

    return ssh


def collect_remote_files(sftp, remote_directory, base_directory=None):
    """Collect relative file paths and sizes from Stage."""

    if base_directory is None:
        base_directory = remote_directory

    files = {}

    for entry in sftp.listdir_attr(remote_directory):
        remote_path = posixpath.join(remote_directory, entry.filename)

        if stat.S_ISDIR(entry.st_mode):
            files.update(
                collect_remote_files(
                    sftp,
                    remote_path,
                    base_directory,
                )
            )

        elif stat.S_ISREG(entry.st_mode):
            relative_path = posixpath.relpath(
                remote_path,
                base_directory,
            )

            files[relative_path] = entry.st_size

    return files


def collect_local_files(local_directory):
    """Collect relative file paths and sizes from Production."""

    local_directory = Path(local_directory)
    files = {}

    for file_path in local_directory.rglob("*"):
        if file_path.is_file():
            relative_path = file_path.relative_to(
                local_directory
            ).as_posix()

            files[relative_path] = file_path.stat().st_size

    return files


def validate_transfer(sftp, remote_source, local_destination):
    """Compare Stage and Production files and their sizes."""

    print("\nStarting transfer validation...")

    source_files = collect_remote_files(
        sftp,
        remote_source,
    )

    destination_files = collect_local_files(
        local_destination,
    )

    missing_files = sorted(
        set(source_files) - set(destination_files)
    )

    extra_files = sorted(
        set(destination_files) - set(source_files)
    )

    size_mismatches = []

    for file_path in sorted(
        set(source_files) & set(destination_files)
    ):
        if source_files[file_path] != destination_files[file_path]:
            size_mismatches.append({
                "file": file_path,
                "stage_size": source_files[file_path],
                "production_size": destination_files[file_path],
            })

    print("\n========== VALIDATION SUMMARY ==========")
    print(f"Stage files       : {len(source_files)}")
    print(f"Production files  : {len(destination_files)}")
    print(f"Missing files     : {len(missing_files)}")
    print(f"Extra files       : {len(extra_files)}")
    print(f"Size mismatches   : {len(size_mismatches)}")
    print("========================================")

    for file_path in missing_files:
        print(f"[MISSING] {file_path}")

    for file_path in extra_files:
        print(f"[EXTRA] {file_path}")

    for mismatch in size_mismatches:
        print(
            f"[SIZE MISMATCH] {mismatch['file']} | "
            f"Stage: {mismatch['stage_size']} | "
            f"Production: {mismatch['production_size']}"
        )

    if missing_files or size_mismatches:
        raise RuntimeError(
            "Transfer validation failed. "
            "External-table creation must not proceed."
        )

    if extra_files:
        print(
            "\nWARNING: Extra files exist in Production. "
            "They have not been deleted."
        )

    return True


def transfer_directory(sftp, remote_source, local_destination, stats):
    """Recursively copy files, skipping unchanged files."""

    local_destination = Path(local_destination)
    local_destination.mkdir(parents=True, exist_ok=True)

    for entry in sftp.listdir_attr(remote_source):
        remote_path = posixpath.join(remote_source, entry.filename)
        local_path = local_destination / entry.filename

        if stat.S_ISDIR(entry.st_mode):
            print(f"[DIRECTORY] {remote_path}")

            transfer_directory(
                sftp,
                remote_path,
                local_path,
                stats,
            )

        elif stat.S_ISREG(entry.st_mode):

            # Check whether the destination file already exists.
            if local_path.exists():

                local_size = local_path.stat().st_size
                remote_size = entry.st_size

                local_mtime = int(local_path.stat().st_mtime)
                remote_mtime = int(entry.st_mtime)

                # Skip files that haven't changed.
                if (
                    local_size == remote_size
                    and local_mtime == remote_mtime
                ):
                    print(f"[SKIPPED] {remote_path}")
                    stats["skipped"] += 1
                    continue

                print(f"[UPDATED] {remote_path}")
                stats["updated"] += 1

            else:
                print(f"[COPIED] {remote_path}")
                stats["copied"] += 1

            # Download to a temporary file first.
            # Replace the destination only after successful download.
            temp_path = local_path.with_name(
                local_path.name + ".download_tmp"
            )

            try:
                sftp.get(remote_path, str(temp_path))

                # Preserve the Stage file's modification timestamp.
                os.utime(
                    temp_path,
                    (entry.st_atime, entry.st_mtime),
                )

                os.replace(temp_path, local_path)

            finally:
                if temp_path.exists():
                    temp_path.unlink()



def transfer_from_stage(stage_config, production_destination):
    print("\n========================================")
    print("     COPY PARQUET FILES ")
    print("========================================")
    password = getpass.getpass(
        f"\nEnter SSH password for {stage_config['username']}@"
        f"{stage_config['host']}: "
    )

    ssh = None

    try:
        print("\nConnecting to Stage server...")

        ssh = create_remote_connection(
            host=stage_config["host"],
            username=stage_config["username"],
            password=password,
            port=stage_config.get("port", 22),
        )

        print("SSH connection established.")

        with ssh.open_sftp() as sftp:
            remote_source = stage_config["source_path"]

            attributes = sftp.stat(remote_source)

            if not stat.S_ISDIR(attributes.st_mode):
                raise NotADirectoryError(
                    f"Stage source is not a directory: {remote_source}"
                )

            destination = Path(production_destination)
            destination.mkdir(parents=True, exist_ok=True)

            stats = {
                "copied": 0,
                "updated": 0,
                "skipped": 0,
            }

            print(f"\nStage source      : {remote_source}")
            print(f"Production target : {destination}")
            print("\nStarting Parquet transfer...\n")

            transfer_directory(
                sftp,
                remote_source,
                destination,
                stats
            )

            validate_transfer(
                sftp,
                remote_source,
                destination,
            )

        print("\n========== TRANSFER SUMMARY ==========")
        print(f"New files copied       : {stats['copied']}")
        print(f"Existing files updated : {stats['updated']}")
        print(f"Unchanged files skipped: {stats['skipped']}")
        print("======================================")

    except Exception as exc:
        print(f"\nParquet transfer failed: {exc}")
        raise

    finally:
        if ssh:
            ssh.close()

        password = None


def main():
    config_path = Path(__file__).parent / "deployment_config.json"

    with open(config_path, "r", encoding="utf-8") as file:
        config = json.load(file)

    stage_config = config["stage"]
    production_destination = config["production"]["parquet_destination"]

    transfer_from_stage(
        stage_config,
        production_destination,
    )


if __name__ == "__main__":
    main()
