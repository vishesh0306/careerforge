import logging
import sys

pipeline_logger = logging.getLogger("careerforge.pipeline")


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )


def log_transition(run_type: str, run_id: int, current_step: str, run_status: str, **extra: object) -> None:
    """Logs a pipeline state transition in one consistent, greppable line:
    'pipeline_transition run_type=X run_id=N step=STEP status=STATUS key=value ...'
    Call this every time a run_type/PipelineRun-like record's step or status changes."""
    details = " ".join(f"{key}={value}" for key, value in extra.items())
    pipeline_logger.info(
        "pipeline_transition run_type=%s run_id=%s step=%s status=%s%s",
        run_type,
        run_id,
        current_step,
        run_status,
        f" {details}" if details else "",
    )
