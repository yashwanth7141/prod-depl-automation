# Parquet Deployment Automation

Automates the deployment of Parquet files from a Stage environment to a Production environment, followed by PostgreSQL external table creation and Parquet Retention Policy registration.

The automation is designed to run directly on the **Production server** and orchestrates the complete deployment workflow through a single Python entry point.

## Features

- **Stage-to-Production transfer:** Connects to the Stage server through SSH/SFTP and recursively transfers Parquet application directories.
- **Transfer validation:** Validates transferred files by comparing relative file paths and file sizes.
- **Incremental transfer:** Skips files that are already up to date and transfers new or modified files.
- **Production permissions:** Applies the configured owner, group, and directory/file permissions.
- **External table creation:** Executes the existing External Table Creation utility against the transferred Parquet application.
- **Retention registration:** Generates a CSV containing Production Parquet file paths and retention dates, then imports it into the Parquet Retention Agent.
- **Execution statistics:** Displays Retention Agent statistics after importing the CSV.
- **Terminal status messages:** Uses colored messages to distinguish deployment progress, success, and failure.

## Deployment Workflow

The automation executes the following steps:

1. Connects to the Stage server using SSH.
2. Transfers the configured Parquet application directory to Production.
3. Validates the transferred files.
4. Applies Production ownership and permissions.
5. Checks the External Table Creation configuration.
6. Creates or reuses the External Table configuration.
7. Executes external table creation in single-application mode.
8. Generates the Production Parquet retention CSV.
9. Imports the CSV into the Parquet Retention Agent.
10. Displays retention statistics.

**Important:** The automation only imports retention records. It does not execute the Retention Agent's deletion process.

## Prerequisites

Ensure the following are available on the Production server:

- Python 3.12
- SSH access from Production to Stage
- Stage server credentials
- Access to the configured Parquet source directory on Stage
- External Table Creation utility installed on Production
- Parquet Retention Agent installed on Production
- Required Python packages specified in `requirements.txt` installed in the selected Python virtual environment
- PostgreSQL connectivity for external table creation
- Required sudo permissions for applying File ownership and permissions

The configured Python interpreter must have the dependencies required by both the External Table Creation utility and the Retention Agent.

## Project Structure

```text
optim-parquet-deployment-automation/
│
├── main.py
├── ssh_transfer.py
├── permissions.py
├── test_permissions.py
│
├── deployment_config.json
├── requirements.txt
├── .gitignore
└── README.md
```

### File Description

| File | Description |
|---|---|
| `main.py` | Main deployment orchestrator |
| `ssh_transfer.py` | SSH/SFTP connection, Parquet transfer, and validation |
| `permissions.py` | Production ownership and permission management |
| `test_permissions.py` | Standalone permission testing |
| `deployment_config.json` | Environment-specific deployment configuration |
| `requirements.txt` | Python dependencies |
| `README.md` | Project documentation |

## Configuration

Before executing the deployment, update `deployment_config.json` with the appropriate Stage and Production environment details.

### Configuration Example

```json
{
    "python_executable": "/path/to/python3.12",

    "stage": {
        "host": "stage-server.example.com",
        "port": 22,
        "username": "stage_user",
        "source_path": "/path/to/stage/parquet/application"
    },

    "production": {
        "parquet_destination": "/path/to/production/parquet"
    },

    "permissions": {
        "owner": "svcoptim",
        "group": "svcoptim",
        "mode": "775"
    },

    "external_table": {
        "application_path": "/path/to/external-table-utility"
    },

    "retention_agent": {
        "application_path": "/path/to/retention-agent",
        "retention_date": "2026-12-31"
    }
}
```

Replace the example values with the actual Production environment configuration.

### Configuration Parameters

| Parameter | Description |
|---|---|
| `python_executable` | Absolute path to the Python 3.12 interpreter used by the utilities |
| `stage.host` | Stage server hostname |
| `stage.port` | SSH port |
| `stage.username` | Stage SSH username |
| `stage.source_path` | Source Parquet application directory on Stage |
| `production.parquet_destination` | Parent directory where the Stage application directory will be transferred |
| `permissions.owner` | Required Production file owner |
| `permissions.group` | Required Production file group |
| `permissions.mode` | Required permission mode |
| `external_table.application_path` | Installed External Table Creation utility directory |
| `retention_agent.application_path` | Installed Parquet Retention Agent directory |
| `retention_agent.retention_date` | Retention date to register for transferred Parquet files (`YYYY-MM-DD`) |

**Note:** The final Production application directory is automatically created using the Stage source directory's name.

For example:

```text
Stage source:
    /nfs/prddroptim/parq_storage/prdm_parq

Production destination:
    /production/parquet

Final Production directory:
    /production/parquet/prdm_parq
```

## Installation

Clone the repository on the Production server:

```bash
git clone <repository-url>
```

Navigate to the project directory:

```bash
cd optim-parquet-deployment-automation
```

Create a virtual environment if required:

```bash
python3.12 -m venv venv
```

Activate the environment:

```bash
source venv/bin/activate
```

Install the project dependencies:

```bash
pip install -r requirements.txt
```

Update `deployment_config.json` with the Production environment details.

## SSH Configuration

The automation prompts for the Stage SSH password whenever a deployment is initiated.

The password is not stored in `deployment_config.json` or printed in the deployment logs.

The Stage server's SSH host key must already be trusted by the Production execution account. The SSH connection uses host-key verification rather than automatically accepting unknown host keys.

## Production Permissions

The automation applies the configured ownership and permissions recursively to the transferred application directory.

For example:

```text
Owner : svcoptim
Group : svcoptim
Mode  : 775
```

If the executing account requires elevated privileges, the Production administrator must configure the necessary sudo permissions.

For non-interactive execution, configure narrowly scoped passwordless sudo permissions for the required ownership and permission commands and approved deployment paths.

## External Table Creation

The automation checks for the External Table Creation utility's `config.json`.

- If the configuration exists and contains valid JSON, it is reused.
- If the configuration is missing, `config_installer.py` is executed to create it.
- The PostgreSQL connection details are configured interactively when the installer runs.
- External table creation is executed in single-application mode against the newly transferred Production Parquet directory.

The automation also checks the generated JSON report to identify reported table errors.

## Parquet Retention Registration

After external table creation, the automation scans the final Production application directory for Parquet files.

It generates the following CSV:

```text
<retention-agent-directory>/input/production_parquet_retention.csv
```

The CSV contains two columns:

```csv
parquet_file_path,retention_date
/path/to/production/parquet/application/table1.parquet,2026-12-31
/path/to/production/parquet/application/table2.parquet,2026-12-31
```

The configured retention date is applied to the discovered Parquet files.

The generated CSV is imported using the Retention Agent's import command, followed by its statistics command.

**Safety:** The deployment automation does not execute the Retention Agent's `run` command and does not delete Parquet files.

## Execution

Run the deployment from the project directory:

```bash
python main.py
```

The automation executes the complete workflow sequentially.

### Expected Execution Stages

```text
========================================
     PARQUET DEPLOYMENT TO PRODUCTION
========================================

[STEP 1/4] Parquet Transfer
[STEP 2/4] Production Permissions
[STEP 3/4] External Table Creation
[STEP 4/4] Retention Registration
```

A successful deployment displays a completion message.

If any deployment step encounters an error, the automation displays a failure message and exits with a non-zero status.

## Important Notes

1. Run the automation from the Production server.
2. Verify the Stage source path and Production destination before starting.
3. Ensure the configured Python interpreter and required dependencies are available.
4. Ensure SSH connectivity and host-key trust are established.
5. Ensure PostgreSQL connectivity and External Table configuration are correct.
6. Ensure the Production execution account has the required directory permissions.
7. Use the correct retention date supplied by the customer.
8. Review the external table creation report and Retention Agent statistics after deployment.
9. The automation does not delete existing Production files that are absent from Stage.
10. The Retention Agent deletion process must be executed separately through its own operational procedure, if required.

<hr>