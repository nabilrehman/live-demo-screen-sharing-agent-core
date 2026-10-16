"""LiveKit Cloud entrypoint for the lean demo agent (agent.py): one session per worker, because each session runs
its own Chromium (~1.5-2 GB). A busy worker rejects the job and LiveKit offers it to another instance."""

import logging
import os

from livekit.agents import JobRequest, cli

import agent

MAX_JOBS = int(os.getenv("MAX_JOBS_PER_WORKER", "1"))
log = logging.getLogger("lean.cloud")
server = agent.server
server._job_memory_warn_mb = float(os.getenv("JOB_MEMORY_WARN_MB", "2500"))


async def _one_at_a_time(req: JobRequest) -> None:
    if len(server.active_jobs) >= MAX_JOBS:
        log.info("rejecting job for room %s: busy", req.room.name)
        await req.reject()
    else:
        await req.accept()


server._request_fnc = _one_at_a_time

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cli.run_app(server)
