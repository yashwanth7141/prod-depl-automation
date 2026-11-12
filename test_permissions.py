
from permissions import apply_permissions

apply_permissions(
    target_path="/home/postgres/yashwanth/deployment_automation_script/prod-depl-automation/test",
    owner="postgres",
    group="postgres",
    mode="775"
)
