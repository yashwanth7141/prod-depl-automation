
import json
import os
import subprocess
import sys
import csv
from pathlib import Path
from datetime import date

from ssh_transfer import transfer_from_stage
from permissions import apply_permissions


# Terminal colors
GREEN = "\033[92m"
RED = "\033[91m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def load_deployment_config():
    """Load and validate deployment configuration."""

    config_path = Path(__file__).parent / "deployment_config.json"

    if not config_path.exists():
        raise FileNotFoundError(
            f"Deployment configuration not found: {config_path}"
        )

    with open(config_path, "r", encoding="utf-8") as file:
        config = json.load(file)

    if not config.get("python_executable"):
        raise ValueError(
            "Missing python_executable in deployment_config.json"
        )

    required_sections = [
        "stage",
        "production",
        "permissions",
        "external_table",
        "retention_agent"
    ]

    for section in required_sections:
        if section not in config:
            raise ValueError(
                f"Missing '{section}' section in deployment_config.json"
            )

    stage_config = config["stage"]
    production_config = config["production"]
    permission_config = config["permissions"]
    external_config = config["external_table"]
    retention_config = config["retention_agent"]

    required_stage_fields = [
        "host",
        "username",
        "source_path",
    ]

    for field in required_stage_fields:
        if not stage_config.get(field):
            raise ValueError(
                f"Missing Stage configuration field: {field}"
            )

    if not production_config.get("parquet_destination"):
        raise ValueError(
            "Missing production.parquet_destination"
        )

    required_permission_fields = [
        "owner",
        "group",
        "mode",
    ]

    for field in required_permission_fields:
        if not permission_config.get(field):
            raise ValueError(
                f"Missing permissions configuration field: {field}"
            )

    required_external_fields = [
        "application_path",
    ]

    for field in required_external_fields:
        if not external_config.get(field):
            raise ValueError(
                f"Missing external_table.{field}"
            )

    required_retention_fields = [
        "application_path",
        "retention_date",
    ]

    for field in required_retention_fields:
        if not retention_config.get(field):
            raise ValueError(
                f"Missing retention_agent.{field}"
            )

    return config


def validate_external_config(config_path):
    """Validate the External Table application's configuration."""

    if not config_path.exists():
        raise FileNotFoundError(
            f"External Table config.json was not created: {config_path}"
        )

    try:
        with open(config_path, "r", encoding="utf-8") as file:
            config = json.load(file)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"External Table config.json contains invalid JSON: {exc}"
        )

    if not isinstance(config, dict):
        raise ValueError(
            "External Table config.json must contain a JSON object."
        )

    print("External Table configuration validated.")


def setup_external_table_config(application_path, python_executable):
    """Run the installer only when config.json is missing."""

    config_path = application_path / "config.json"
    installer_path = application_path / "config_installer.pyc"

    print("\nChecking External Table configuration...")

    if config_path.exists():
        print("Existing config.json found. Reusing configuration.")
        validate_external_config(config_path)
        return

    print("config.json not found.")
    print("Starting External Table configuration installer...")

    if not installer_path.is_file():
        raise FileNotFoundError(
            f"Configuration installer not found: {installer_path}"
        )

    result = subprocess.run(
        [python_executable, str(installer_path)],
        cwd=str(application_path),
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "External Table configuration installer failed "
            f"with exit code {result.returncode}."
        )

    validate_external_config(config_path)

    print("External Table configuration setup completed.")


def get_report_snapshot(reports_directory):
    """Capture existing JSON report metadata before execution."""

    snapshot = {}

    if not reports_directory.exists():
        return snapshot

    for report_path in reports_directory.glob("*.json"):
        stat_result = report_path.stat()
        snapshot[report_path] = (
            stat_result.st_mtime_ns,
            stat_result.st_size,
        )

    return snapshot


def validate_external_table_report(reports_directory, previous_reports):
    """Find and validate the JSON report generated by the latest run."""

    if not reports_directory.exists():
        raise RuntimeError(
            "External Table application did not generate a reports directory."
        )

    new_reports = []

    for report_path in reports_directory.glob("*.json"):
        stat_result = report_path.stat()
        current_metadata = (
            stat_result.st_mtime_ns,
            stat_result.st_size,
        )

        if previous_reports.get(report_path) != current_metadata:
            new_reports.append(report_path)

    if not new_reports:
        raise RuntimeError(
            "External Table execution finished, but no new JSON report "
            "was generated."
        )

    latest_report = max(
        new_reports,
        key=lambda path: path.stat().st_mtime_ns,
    )

    print(f"\nExternal Table report: {latest_report}")

    try:
        with open(latest_report, "r", encoding="utf-8") as file:
            report = json.load(file)
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(
            f"Unable to read External Table report: {exc}"
        )

    if not isinstance(report, dict):
        raise RuntimeError(
            "External Table report does not contain a JSON object."
        )

    if not report.get("schemas"):
        raise RuntimeError(
            "External Table report does not contain any processed schemas."
        )

    # The External Table application maintains this counter.
    # A non-zero value indicates table creation errors.
    error_count = report.get("total_tables_errored_out", 0)

    try:
        error_count = int(error_count)
    except (TypeError, ValueError):
        raise RuntimeError(
            "Unable to validate total_tables_errored_out in the report."
        )

    if error_count > 0:
        raise RuntimeError(
            f"External Table creation completed with {error_count} "
            "table error(s). Check the generated JSON report and logs."
        )

    print("External Table JSON report is readable.")
    print("No table errors reported by the application.")

    return latest_report


def run_external_table_creation(external_config, python_executable, production_destination):
    """Configure and execute the External Table application."""

    application_path = Path(
        external_config["application_path"]
    ).expanduser().resolve()

    python_executable = Path(
        python_executable
    ).expanduser().resolve()

    main_script = application_path / "main.pyc"
    reports_directory = application_path / "reports"

    print("\n========================================")
    print("     EXTERNAL TABLE CREATION")
    print("========================================")

    if not application_path.is_dir():
        raise FileNotFoundError(
            f"External Table application directory not found: "
            f"{application_path}"
        )

    if not python_executable.is_file():
        raise FileNotFoundError(
            f"Python executable not found: {python_executable}"
        )

    if not os.access(python_executable, os.X_OK):
        raise PermissionError(
            f"Python executable is not executable: {python_executable}"
        )

    if not main_script.is_file():
        raise FileNotFoundError(
            f"External Table main.pyc not found: {main_script}"
        )

    print(f"Application path : {application_path}")
    print(f"Python           : {python_executable}")
    print(f"Parquet path     : {production_destination}")

    # STEP 1: Check/install External Table configuration.
    setup_external_table_config(
        application_path,
        python_executable,
    )

    # STEP 2: Capture reports before execution.
    previous_reports = get_report_snapshot(reports_directory)

    # STEP 3: Execute single-application mode.
    print("\nStarting External Table creation...")
    print("Selected mode: Single Application")

    application_input = (
        f"1\n"
        f"{production_destination}\n"
    )

    result = subprocess.run(
        [str(python_executable), str(main_script)],
        cwd=str(application_path),
        input=application_input,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "External Table application failed "
            f"with exit code {result.returncode}."
        )

    print("\nExternal Table application process completed.")

    # STEP 4: Validate the generated report.
    validate_external_table_report(
        reports_directory,
        previous_reports,
    )

    print("\nExternal Table creation stage completed.")



def generate_retention_csv(
    production_destination,
    retention_config
):
    """Generate a two-column CSV for Production Parquet files."""

    parquet_root = Path(production_destination).resolve()

    retention_date = retention_config["retention_date"]

    try:
        date.fromisoformat(retention_date)
    except ValueError:
        raise ValueError(
            "Invalid retention_date. Expected YYYY-MM-DD."
        )

    if not parquet_root.is_dir():
        raise FileNotFoundError(
            f"Production Parquet directory not found: {parquet_root}"
        )

    input_directory = (
        Path(retention_config["application_path"])
        / "input"
    )

    input_directory.mkdir(parents=True, exist_ok=True)

    csv_path = input_directory / "production_parquet_retention.csv"

    parquet_files = sorted(
        file_path
        for file_path in parquet_root.rglob("*.parquet")
        if file_path.is_file()
        and not any(
            part.startswith(".")
            for part in file_path.relative_to(parquet_root).parts
        )
    )

    if not parquet_files:
        raise RuntimeError(
            f"No Parquet files found under {parquet_root}"
        )

    with open(
        csv_path,
        "w",
        newline="",
        encoding="utf-8"
    ) as csv_file:

        writer = csv.writer(csv_file)

        writer.writerow([
            "parquet_file_path",
            "retention_date"
        ])

        for parquet_file in parquet_files:
            writer.writerow([
                str(parquet_file),
                retention_date
            ])

    print("\nRetention CSV generated successfully.")
    print(f"CSV path       : {csv_path}")
    print(f"Parquet files  : {len(parquet_files)}")
    print(f"Retention date : {retention_date}")

    return csv_path


def run_retention_agent(
    retention_config,
    python_executable,
    production_destination
):
    """Generate the retention CSV, import it, and display statistics."""

    print("\n========================================")
    print("     PARQUET RETENTION AGENT")
    print("========================================")

    application_path = Path(
        retention_config["application_path"]
    ).expanduser().resolve()

    python_executable = Path(
        python_executable
    ).expanduser().resolve()

    main_script = application_path / "main.pyc"

    if not application_path.is_dir():
        raise FileNotFoundError(
            f"Retention Agent directory not found: {application_path}"
        )

    if not python_executable.is_file():
        raise FileNotFoundError(
            f"Python executable not found: {python_executable}"
        )

    if not main_script.is_file():
        raise FileNotFoundError(
            f"Retention Agent main.pyc not found: {main_script}"
        )

    # STEP 1: Generate CSV.
    print("\n[STEP 1/3] Generate Retention CSV")

    csv_path = generate_retention_csv(
        production_destination,
        retention_config
    )

    # STEP 2: Import CSV.
    print("\n[STEP 2/3] Import Retention Records")

    import_command = [
        str(python_executable),
        str(main_script),
        "import",
        str(csv_path)
    ]

    import_result = subprocess.run(
        import_command,
        cwd=str(application_path),
        check=False
    )

    if import_result.returncode != 0:
        raise RuntimeError(
            "Retention Agent CSV import failed "
            f"with exit code {import_result.returncode}."
        )

    print("\nRetention CSV import process completed.")

    # STEP 3: Display statistics.
    print("\n[STEP 3/3] Retention Agent Statistics")

    stats_command = [
        str(python_executable),
        str(main_script),
        "stats"
    ]

    stats_result = subprocess.run(
        stats_command,
        cwd=str(application_path),
        check=False
    )

    if stats_result.returncode != 0:
        raise RuntimeError(
            "Retention Agent statistics command failed "
            f"with exit code {stats_result.returncode}."
        )

    print("\nRetention Agent integration completed.")



def run_deployment():
    """Execute the Stage-to-Production deployment workflow."""

    print("\n========================================")
    print(f"{CYAN}     PARQUET DEPLOYMENT TO PRODUCTION{RESET}")
    print("========================================")

    config = load_deployment_config()

    python_executable = config["python_executable"]
    stage_config = config["stage"]
    production_config = config["production"]
    permission_config = config["permissions"]
    external_config = config["external_table"]
    retention_config = config["retention_agent"]

    # Production destination is the parent directory.
    destination_root = Path(
        production_config["parquet_destination"]
    ).expanduser().resolve()

    # Extract the Stage application folder name.
    source_folder_name = Path(
        stage_config["source_path"].rstrip("/")
    ).name

    if not source_folder_name:
        raise ValueError("Invalid Stage source_path.")

    # Final destination includes the Stage application folder.
    destination = destination_root / source_folder_name

    print(f"\nProduction application path : {destination}")

    # STEP 1: Transfer
    print(f"\n {YELLOW}---[STEP 1/4] Stage-to-Production Parquet Transfer---{RESET}")

    transfer_from_stage(stage_config, destination)

    print(f"\n{GREEN}Stage-to-Production parquet file transfer completed.{RESET}")
    print(f"\n{GREEN}Transfer validation passed.{RESET}")

    # STEP 2: Permissions
    print(f"\n {YELLOW}---[STEP 2/4] Apply Production Permissions---{RESET}")

    apply_permissions(
        target_path=destination,
        owner=permission_config["owner"],
        group=permission_config["group"],
        mode=permission_config["mode"],
    )

    print(f"\n{GREEN}Production permissions applied.{RESET}")

    # STEP 3: External Table creation
    print(f"\n {YELLOW}---[STEP 3/4] External Table Creation---{RESET}")

    run_external_table_creation(
        external_config=external_config,
        python_executable=python_executable,
        production_destination=destination,
    )

    print(f"\n{GREEN}External Table creation completed successfully.{RESET}")

    # STEP 4: Retention Agent
    print(f"\n {YELLOW}---[STEP 4/4] Parquet Retention Agent---{RESET}")

    run_retention_agent(
        retention_config=retention_config,
        python_executable=python_executable,
        production_destination=destination
    )

    print(f"\n{GREEN}Parquet Retention Policy applied successfully.{RESET}")

    print("\n========================================")
    print(f"{GREEN}     DEPLOYMENT STEPS COMPLETED{RESET}")
    print("========================================")



def main():
    try:
        run_deployment()

    except Exception as exc:
        print("\n========================================")
        print(f"{RED}     DEPLOYMENT FAILED{RESET}")
        print("========================================")
        print(f"Reason: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
