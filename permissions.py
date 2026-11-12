
import os
import pwd
import grp
import shutil
import subprocess
from pathlib import Path


def run_sudo(command):
    """
    Execute a command using non-interactive sudo.
    No sudo password prompt is allowed.
    """
    sudo_path = shutil.which("sudo")

    if not sudo_path:
        raise RuntimeError("sudo executable was not found.")

    try:
        result = subprocess.run(
            [sudo_path, "-n", *command],
            capture_output=True,
            text=True,
            check=True
        )
        return result

    except subprocess.CalledProcessError as exc:
        error = exc.stderr.strip() or exc.stdout.strip()

        raise RuntimeError(
            f"Permission command failed: {' '.join(command)}\n"
            f"Details: {error}\n"
            "Check the sudo permissions configured for this deployment."
        ) from exc


def check_ownership(path, owner, group):
    """
    Check whether all files and directories have the expected owner/group.
    """
    expected_uid = pwd.getpwnam(owner).pw_uid
    expected_gid = grp.getgrnam(group).gr_gid

    paths = [path]

    for root, directories, files in os.walk(path):
        paths.extend(Path(root) / name for name in directories)
        paths.extend(Path(root) / name for name in files)

    for item in paths:
        if item.is_symlink():
            continue

        file_stat = item.stat()

        if (
            file_stat.st_uid != expected_uid
            or file_stat.st_gid != expected_gid
        ):
            return False

    return True


def change_ownership(path, owner, group):
    """
    Change ownership recursively only when required.
    """
    if check_ownership(path, owner, group):
        print(f"\nOwnership already correct: {owner}:{group}")
        return

    print(f"\nChanging ownership to {owner}:{group}...")

    run_sudo([
        "chown",
        "-R",
        f"{owner}:{group}",
        str(path)
    ])

    print("Ownership updated successfully.")


def change_permissions(path, mode):
    """
    Apply permissions recursively.
    First try without sudo. Use restricted sudo if required.
    """
    permission = int(mode, 8)

    paths = [path]

    for root, directories, files in os.walk(path):
        paths.extend(Path(root) / name for name in directories)
        paths.extend(Path(root) / name for name in files)

    try:
        for item in paths:
            if item.is_symlink():
                continue

            item.chmod(permission)

        print(f"Permissions applied successfully: {mode}")

    except PermissionError:
        print("Elevated privileges required for chmod.")

        run_sudo([
            "chmod",
            "-R",
            mode,
            str(path)
        ])

        print(f"Permissions applied successfully: {mode}")


def apply_permissions(target_path, owner, group, mode="775"):
    """
    Apply configured ownership and permissions to the target directory.
    """

    print("\n========================================")
    print("     APPLY FILE PERMISSIONS")
    print("========================================")

    path = Path(target_path).resolve()

    if not path.exists():
        raise FileNotFoundError(
            f"Permission target does not exist: {path}"
        )

    if not path.is_dir():
        raise NotADirectoryError(
            f"Permission target is not a directory: {path}"
        )

    # Validate configured owner and group.
    pwd.getpwnam(owner)
    grp.getgrnam(group)

    print("\nApplying Production permissions...")
    print(f"Target : {path}")
    print(f"Owner  : {owner}")
    print(f"Group  : {group}")
    print(f"Mode   : {mode}")

    change_ownership(path, owner, group)
    change_permissions(path, mode)
