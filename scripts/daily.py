"""每日任务总入口（阶段四）。

云服务器上由 cron 在每天 08:00（北京时间）调用：
    0 8 * * * /path/to/radar/.venv/bin/python /path/to/radar/scripts/daily.py

流程：采集（collect） -> 评分（score）。
日志写入 logs/daily-YYYY-MM-DD.log（北京时间日期），cron 失败会发邮件给服务器 root
（建议在 crontab 加 MAILTO）。退出码：0 成功 / 1 部分成功 / 2 失败。
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

LOGS = BASE / "logs"
BEIJING = ZoneInfo("Asia/Shanghai")


def log(msg: str) -> None:
    ts = datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)


def run_step(name: str, script: str) -> bool:
    log(f"开始步骤：{name}")
    env = dict(os.environ)
    # 确保子进程用项目 venv 的 python
    proc = subprocess.run(
        [str(BASE / ".venv" / "bin" / "python"), str(BASE / "scripts" / script)],
        cwd=str(BASE), env=env, capture_output=True, text=True, timeout=1800,
    )
    if proc.stdout:
        for line in proc.stdout.strip().splitlines()[-15:]:
            log(f"  [{name}] {line}")
    if proc.returncode != 0:
        log(f"步骤失败：{name}（退出码 {proc.returncode}）")
        if proc.stderr:
            log(f"  错误：{proc.stderr.strip()[-2000:]}")
        return False
    log(f"步骤完成：{name}")
    return True


def main() -> int:
    LOGS.mkdir(parents=True, exist_ok=True)
    today = datetime.now(BEIJING).strftime("%Y-%m-%d")
    logfile = LOGS / f"daily-{today}.log"

    # 把 print 重定向到日志文件（同时保留控制台）
    import io

    class Tee(io.TextIOBase):
        def __init__(self, *streams):
            self.streams = streams

        def write(self, s):
            for st in self.streams:
                st.write(s)
            return len(s)

        def flush(self):
            for st in self.streams:
                st.flush()

    logf = open(logfile, "a", encoding="utf-8")
    old_stdout = sys.stdout
    sys.stdout = Tee(old_stdout, logf)
    try:
        log("===== 每日任务开始 =====")
        ok_collect = run_step("采集", "collect.py")
        ok_score = run_step("评分", "score.py") if ok_collect else False
        if ok_collect and ok_score:
            log("===== 每日任务成功 =====")
            return 0
        log("===== 每日任务部分失败 =====")
        return 1
    except Exception as e:  # noqa: BLE001
        log(f"每日任务异常：{e}")
        return 2
    finally:
        sys.stdout = old_stdout
        logf.close()


if __name__ == "__main__":
    sys.exit(main())
