"""
Module implements high level logic of MIPS workflows
"""
import logging
from concurrent import futures
from datetime import datetime, timezone
from typing import Callable, Optional

import polars as pl

from lib.gateway import google_sheets, mips, telegram
from lib.internal import configurator, utils

log = logging.getLogger("main_logger")


# workflow names
PATCH_BACKLIGHT_WORKFLOW_NAME = "patch_backlight"
# other constants
_PATCH_BACKLIGHT_PARAM_NAMES = {
    "enable": mips.RPC_BACKLIGHT_ON_STATUS,
    "disable": mips.RPC_BACKLIGHT_OFF_STATUS,
}
# sheet columns
TOGGLE_COL = "toggle"
HOURS_TO_RUN_COL = "hours_to_run"
WORKFLOW_COL = "workflow"
ARGS_COL = "arguments"
MODE_COL = "mode"
# other constants
SHADOW_MODE_NAME = "shadow"
TOGGLE_ON = "on"
ALL_HOURS = "all"


class WorkflowError(Exception):
    "Generic error raise by methods of App"
    pass


class WorkflowTask:
    "Abstraction encapsulating workflow callable and arguments"
    def __init__(self, executable: Callable, args: list):
        "Constructor"
        self.executable = executable
        self.args = args


class WorkflowResult:
    "Represents workflow execution result"
    def __init__(
        self,
        workflow: str,
        start_ts: str,
        mode: str,
        end_ts: Optional[str] = None,
        error: Optional[Exception] = None
    ):
        "Constructor"
        self.workflow = workflow
        self.start_ts = start_ts
        self.end_ts = end_ts
        self.error = error
        self.mode = mode

    def to_dict(self) -> dict:
        "Converts instance to a dict"
        return {
            "workflow": self.workflow,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "error": self.error,
            "mode": self.mode
        }


class App:
    "Abstraction that uses lower level objects to execute MIPS tasks"  
    def __init__(
            self,
            sheets: google_sheets.GoogleSheetsGateway,
            mips_api_client: mips.MIPSClient,
            telegram: telegram.TelegramGateway,
            cfg: configurator.Configurator
        ):
        """Constructs the application.

        Args:
            sheets (google_sheets.GoogleSheetsGateway)
            mips_api_client (mips.MIPSClient)
        """
        self.sheets = sheets
        self.mips_api_client = mips_api_client
        self.telegram = telegram
        self.cfg = cfg

    def _task_name_to_executable(self, name: str):
        if name == PATCH_BACKLIGHT_WORKFLOW_NAME:
            return self.patch_backlight        

    def _task_args_to_workflow_args(self, task: dict) -> list:
        args = [a.strip() for a in task[ARGS_COL].split(",")]
        cnt_args = len(args)
        if task[WORKFLOW_COL] == PATCH_BACKLIGHT_WORKFLOW_NAME:
            if cnt_args > 1:
                raise ValueError("wrong number of args")
            return [task[MODE_COL], _PATCH_BACKLIGHT_PARAM_NAMES[args[0]]]
    
    def _task_data_to_workflow_task(self, task: dict) -> tuple:
        if (executable := self._task_name_to_executable(task[WORKFLOW_COL])) is None:  # noqa: E501
            return None, NotImplementedError(f"{task[WORKFLOW_COL]} is not supported")
        try:
            return WorkflowTask(
                executable=executable,
                args=self._task_args_to_workflow_args(task=task)
            ), None
        except Exception as e:
            return None, e
    
    def execute_tasks(self) -> Exception:
        """Main entry point of the app. Steps:
            1. Read control panel from gsheet.
            2. Parse control panel to tasks to be completed based on toggle and hour.
            3. Execute tasks concurrently (thread per task).
            4. Append results to spreadsheet.

        Returns:
            error if any
        """
        task_data, e = self.sheets.read_sheet(
            sheet_id=self.cfg.sheets.spreadsheet,
            tab_name=self.cfg.sheets.tabs["control_panel"]["name"],
            as_df=True,
            schema=self.cfg.sheets.tabs["control_panel"]["schema"]
        )
        if e is not None:
            return WorkflowError(f"execute_tasks failed to fetch tasks from sheet: {e}")  # noqa: E501
        log.info("fetched %s tasks from sheet", len(task_data))
        task_data = task_data.filter(
            # toggle is on
            (pl.col(TOGGLE_COL)==TOGGLE_ON)
            & (
                # either hour matches
                pl.col(HOURS_TO_RUN_COL).str.to_lowercase()
                .str.contains(str(datetime.now(tz=timezone.utc).hour))
                # all hours
                | pl.col(HOURS_TO_RUN_COL).str.to_lowercase().
                str.contains(ALL_HOURS) 
            )
        )
        if len(task_data) == 0:
            log.info("no enabled tasks, nothing to do")
            return
        
        log.info("%s tasks to execute after filtering", len(task_data))
        with futures.ThreadPoolExecutor(max_workers=len(task_data)) as ex:
            workflows = []
            for task in task_data.to_dicts():
                wf_task, e = self._task_data_to_workflow_task(
                    task=task
                )
                if e is not None:
                    log.info("task %s parsing error: %s", e)
                    continue
                workflows.append(ex.submit(
                    wf_task.executable, *wf_task.args
                ))
            # exceptions are handled downstream so no try / except here
            results = [fut.result() for fut in futures.as_completed(workflows)]
        log.info("%s tasks executed. result count: %s",
                 len(workflows), len(results))
        e = self.sheets.append_data(
            sheet_id=self.cfg.sheets.spreadsheet,
            tab_name=self.cfg.sheets.tabs["execute_logs"]["name"],
            data=pl.DataFrame(data=[r.to_dict() for r in results]),
            row_limit=self.cfg.sheets.tabs["execute_logs"]["row_limit"],
            schema=self.cfg.sheets.tabs["execute_logs"]["schema"]
        )
        if e is not None:
            return WorkflowError(f"execute_tasks failed to append task logs to sheet: {e}")  # noqa: E501
        log.info("task execution data pasted to sheet")

    def patch_backlight(self, mode: str, switch_status: int) -> Exception:
        """Executes patch_backlight workflow. Steps:
            1. Get devices from mips API.
            2. Patch backlight to switch status for each device from step 1.
            3. Append results to gsheet.

        Args:
            mode (str): operation mode (shadow means to write calls to the API is made.)
            switch_status (int): backlight status to set.

        Returns:
            dict describing results.
        """  # noqa: E501
        status_name = mips.BACKLIGHT_PARAM_TO_NAME[switch_status]
        log.info(
            "executing patch_backlight workflow, mode: %s, switch_status: %s",
            mode, status_name
        )
        result = WorkflowResult(
            workflow=PATCH_BACKLIGHT_WORKFLOW_NAME,
            start_ts=utils.get_current_timestamp(),
            mode=mode
        )
        devices, e = self.mips_api_client.get_devices()
        log.info("fetched %s devices", len(devices))
        if e is not None:
            result.error = WorkflowError(f"patch_backlight failed to get devices: {e}")
            result.end_ts = utils.get_current_timestamp()
            return result
        devices = {int(device["id"]) for device in devices}
        log.info("converted devices to a list of ids")
        results = self.mips_api_client.patch_backlight_and_validate_bulk(
            devices=list(devices),
            switch_status=switch_status,
            shadow_mode=(mode == SHADOW_MODE_NAME)
        )
        log.info("bulk patched %s devices and got %s results",
                 len(devices), len(results))
        e = self.sheets.append_data(
            sheet_id=self.cfg.sheets.spreadsheet,
            tab_name=self.cfg.sheets.tabs["patch_backlight_logs"]["name"],
            data=pl.DataFrame(data=[r.to_dict() for r in results]),
            row_limit=self.cfg.sheets.tabs["patch_backlight_logs"]["row_limit"],
            schema=self.cfg.sheets.tabs["patch_backlight_logs"]["schema"]
        )
        result.end_ts = utils.get_current_timestamp()
        if e is not None:
            result.error = WorkflowError(f"patch_backlight failed to get devices: {e}")  # noqa: E501
            self.telegram.send_message(
                msg=f"patch_backlight workflow resulted in an error: {result.error}", # noqa: E501
                user_to_tag=self.cfg.telegram.user_to_tag
            )
        log.info("pasted results to spreadsheet")
        self.telegram.send_message(
            msg=f"patch_backlight workflow success. mode: {mode}. switch_status: {status_name}",  # noqa: E501
            user_to_tag=self.cfg.telegram.user_to_tag
        )
        return result

    
    
