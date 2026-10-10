"""Worker entry point: APScheduler loop.

Phase 1 only registers a heartbeat so the worker container stays up and proves the
scheduler runs. Phase 10 adds the pipeline, FIRMS, Nightfire, emission-rate and
baseline jobs using the times in config/settings.yaml `schedule`.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from app.settings import get_settings

log = logging.getLogger("worker")


def heartbeat() -> None:
    settings = get_settings()
    log.info("worker alive (data_mode=%s, region=%s)", settings.data_mode, settings.config.region.name)


def build_scheduler() -> BlockingScheduler:
    cfg = get_settings().config
    scheduler = BlockingScheduler(timezone=cfg.schedule["daily_tz"])
    scheduler.add_job(heartbeat, "interval", minutes=cfg.schedule.get("heartbeat_minutes", 10), id="heartbeat")
    return scheduler


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    heartbeat()
    build_scheduler().start()


if __name__ == "__main__":
    main()
