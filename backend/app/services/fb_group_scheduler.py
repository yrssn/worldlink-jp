"""Facebook 群组定时拉取调度器。

支持：
1. 定时任务管理（cron / interval）
2. Apify Key 自动轮转（额度不足自动切换）
3. 失败重试与自动禁用
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.apify_key import ApifyKey
from app.models.fb_group_scrape import (
    FbGroupPullTask,
    FbGroupPullTaskStatus,
    FbGroupScheduleTask,
    FbGroupScheduleTaskStatus,
)
from app.services import apify_service


class FbGroupScheduler:
    """Facebook 群组定时拉取调度器。"""

    def __init__(self) -> None:
        self.scheduler: BackgroundScheduler | None = None
        self._running = False

    def start(self) -> None:
        """启动调度器。"""
        if self._running:
            return
        self.scheduler = BackgroundScheduler()
        self.scheduler.start()
        self._running = True
        logger.info("[FbGroupScheduler] Started")
        self._load_all_schedules()

    def stop(self) -> None:
        """停止调度器。"""
        if not self._running or not self.scheduler:
            return
        self.scheduler.shutdown()
        self._running = False
        logger.info("[FbGroupScheduler] Stopped")

    def _load_all_schedules(self) -> None:
        """从数据库加载所有活跃的定时任务。"""
        db = SessionLocal()
        try:
            schedules = (
                db.query(FbGroupScheduleTask)
                .filter(FbGroupScheduleTask.status == FbGroupScheduleTaskStatus.active)
                .all()
            )
            for schedule in schedules:
                self._register_schedule(schedule)
        finally:
            db.close()

    def _register_schedule(self, schedule: FbGroupScheduleTask) -> None:
        """注册单个定时任务到 APScheduler。"""
        if not self.scheduler:
            return

        job_id = f"fb_group_schedule_{schedule.id}"

        # 移除已存在的同名任务
        try:
            self.scheduler.remove_job(job_id)
        except Exception:
            pass

        try:
            if schedule.schedule_type == "cron":
                # schedule_config 应为 {"cron": "0 10 * * *"}
                cron_expr = schedule.schedule_config.get("cron", "0 10 * * *")
                trigger = CronTrigger.from_crontab(cron_expr)
            elif schedule.schedule_type == "interval":
                # schedule_config 应为 {"hours": 24} 或 {"days": 1, "hours": 12} 等
                trigger = IntervalTrigger(**schedule.schedule_config)
            else:
                logger.warning("[FbGroupScheduler] Unknown schedule_type: {}", schedule.schedule_type)
                return

            self.scheduler.add_job(
                self._execute_schedule,
                trigger=trigger,
                id=job_id,
                args=(schedule.id,),
                replace_existing=True,
                coalesce=True,
                max_instances=1,
            )
            logger.info("[FbGroupScheduler] Registered schedule#{} ({})", schedule.id, schedule.schedule_type)
        except Exception as e:
            logger.error("[FbGroupScheduler] Failed to register schedule#{}: {}", schedule.id, e)

    def _execute_schedule(self, schedule_id: int) -> None:
        """执行定时任务。"""
        db = SessionLocal()
        try:
            schedule = db.query(FbGroupScheduleTask).filter(FbGroupScheduleTask.id == schedule_id).first()
            if not schedule:
                logger.warning("[FbGroupScheduler] Schedule#{} not found", schedule_id)
                return

            if schedule.status != FbGroupScheduleTaskStatus.active:
                logger.info("[FbGroupScheduler] Schedule#{} is not active ({})", schedule_id, schedule.status)
                return

            # 构建拉取参数，支持增量拉取
            pull_params = dict(schedule.pull_params or {})

            # 如果上次任务成功开始，自动设置 only_posts_newer_than 为上次开始前 5 分钟
            # 配合帖子唯一约束去重，避免任务运行期间的新帖在下一次被漏掉。
            if schedule.last_task_id:
                last_task = db.query(FbGroupPullTask).filter(
                    FbGroupPullTask.id == schedule.last_task_id
                ).first()
                if last_task and last_task.status == FbGroupPullTaskStatus.done and last_task.started_at:
                    since = last_task.started_at - timedelta(minutes=5)
                    pull_params["only_posts_newer_than"] = since.replace(microsecond=0).isoformat()
                    pull_params["auto_only_posts_newer_than"] = True
                    logger.info(
                        "[FbGroupScheduler] Schedule#{} incremental fetch from {}",
                        schedule_id, pull_params["only_posts_newer_than"]
                    )

            # 创建拉取任务
            task = FbGroupPullTask(
                config_id=schedule.config_id,
                created_by_id=schedule.created_by_id,
                status=FbGroupPullTaskStatus.pending,
                params=pull_params,
            )
            db.add(task)
            db.flush()
            task_id = task.id

            schedule.last_run_at = datetime.utcnow()
            schedule.last_task_id = task_id
            db.commit()

            logger.info("[FbGroupScheduler] Created pull task#{} for schedule#{}", task_id, schedule_id)

            # 后台执行拉取（异步）
            import threading
            t = threading.Thread(target=self._run_pull_task_bg, args=(task_id, schedule_id), daemon=True)
            t.start()
        except Exception as e:
            logger.exception("[FbGroupScheduler] Error executing schedule#{}: {}", schedule_id, e)
        finally:
            db.close()

    def _run_pull_task_bg(self, task_id: int, schedule_id: int) -> None:
        """后台执行拉取任务（与 fb_group_scrape.py 中的逻辑类似）。"""
        from app.api.v1.fb_group_scrape import _run_pull_task_bg as run_pull_task_bg

        try:
            run_pull_task_bg(task_id)
        except Exception as e:
            logger.error("[FbGroupScheduler] Pull task#{} failed: {}", task_id, e)

        # 更新定时任务的失败计数
        db = SessionLocal()
        try:
            task = db.query(FbGroupPullTask).filter(FbGroupPullTask.id == task_id).first()
            schedule = db.query(FbGroupScheduleTask).filter(FbGroupScheduleTask.id == schedule_id).first()

            if not schedule:
                return

            if task and task.status == FbGroupPullTaskStatus.failed:
                schedule.consecutive_failures += 1
                logger.warning(
                    "[FbGroupScheduler] Schedule#{} consecutive failures: {}",
                    schedule_id,
                    schedule.consecutive_failures,
                )

                # 超过最大失败次数则自动禁用
                if schedule.consecutive_failures >= schedule.max_consecutive_failures:
                    schedule.status = FbGroupScheduleTaskStatus.disabled
                    logger.error(
                        "[FbGroupScheduler] Schedule#{} disabled due to {} consecutive failures",
                        schedule_id,
                        schedule.consecutive_failures,
                    )
            else:
                # 成功则重置失败计数
                schedule.consecutive_failures = 0

            db.commit()
        except Exception as e:
            logger.exception("[FbGroupScheduler] Error updating schedule#{}: {}", schedule_id, e)
        finally:
            db.close()

    def add_schedule(self, schedule: FbGroupScheduleTask) -> None:
        """添加新的定时任务。"""
        if schedule.status == FbGroupScheduleTaskStatus.active:
            self._register_schedule(schedule)

    def remove_schedule(self, schedule_id: int) -> None:
        """移除定时任务。"""
        if not self.scheduler:
            return
        job_id = f"fb_group_schedule_{schedule_id}"
        try:
            self.scheduler.remove_job(job_id)
            logger.info("[FbGroupScheduler] Removed schedule#{}", schedule_id)
        except Exception:
            pass

    def update_schedule(self, schedule: FbGroupScheduleTask) -> None:
        """更新定时任务。"""
        self.remove_schedule(schedule.id)
        if schedule.status == FbGroupScheduleTaskStatus.active:
            self._register_schedule(schedule)


# 全局调度器实例
fb_group_scheduler = FbGroupScheduler()
