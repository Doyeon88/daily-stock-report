"""
Unit tests for scheduler/daily_task.py
"""

import os
import subprocess
import sys
from unittest.mock import MagicMock

import pytest
import schedule

from scheduler import daily_task


class _StopLoop(Exception):
    pass


def test_job_is_scheduled_in_configured_timezone(monkeypatch):
    monkeypatch.setattr(daily_task.time, 'sleep', MagicMock(side_effect=_StopLoop))
    schedule.clear()
    try:
        with pytest.raises(_StopLoop):
            daily_task.start_scheduler()

        job = schedule.jobs[0]
        assert str(job.at_time_zone) == daily_task.TIMEZONE
        # 09:00 in Asia/Seoul, not 09:00 in the server's local time
        assert job.next_run.astimezone(job.at_time_zone).strftime('%H:%M') == daily_task.DAILY_REPORT_TIME
    finally:
        schedule.clear()


def test_run_daily_report_uses_absolute_main_path(monkeypatch):
    run = MagicMock(return_value=MagicMock(returncode=0))
    monkeypatch.setattr(daily_task.subprocess, 'run', run)

    assert daily_task.run_daily_report() is True

    args, kwargs = run.call_args
    assert args[0][1] == os.path.join(daily_task.PROJECT_ROOT, 'main.py')
    assert kwargs['cwd'] == daily_task.PROJECT_ROOT


def test_script_imports_when_only_its_own_directory_is_on_sys_path(tmp_path):
    """`python scheduler/daily_task.py` puts scheduler/ (not the project root) on sys.path"""
    scheduler_dir = os.path.dirname(os.path.abspath(daily_task.__file__))
    code = (
        "import sys; "
        f"sys.path[:] = [p for p in sys.path if p not in ('', {daily_task.PROJECT_ROOT!r})]; "
        f"sys.path.insert(0, {scheduler_dir!r}); "
        "import daily_task"
    )

    result = subprocess.run(
        [sys.executable, '-c', code], cwd=tmp_path, capture_output=True, text=True
    )

    assert result.returncode == 0, result.stderr
