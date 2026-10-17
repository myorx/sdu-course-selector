"""Retry course-selection requests against SDU's own course system.

All session cookies and course IDs are read from an ignored local config file.
"""

import argparse
import json
import logging
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
HOST = "bkzhjx.wh.sdu.edu.cn"
LOG = logging.getLogger("course_choose")


def validate_url(value, label):
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname != HOST:
        raise ValueError(f"{label} must be an HTTPS URL on {HOST}")
    return value


def load_config(path):
    with path.open(encoding="utf-8") as handle:
        config = json.load(handle)

    config["operation_url"] = validate_url(config["operation_url"], "operation_url")
    config["referer_url"] = validate_url(config["referer_url"], "referer_url")
    if not urlparse(config["operation_url"]).path.startswith("/jsxsd/xsxkkc/"):
        raise ValueError("operation_url must point to an SDU course-selection operation")

    cookies = config.get("cookies")
    if not isinstance(cookies, dict) or not cookies:
        raise ValueError("cookies must be a non-empty object")
    if any(not isinstance(k, str) or not isinstance(v, str) or not v or "REPLACE" in v for k, v in cookies.items()):
        raise ValueError("replace the example cookie values in config.json")

    courses = config.get("courses")
    if not isinstance(courses, list) or not courses:
        raise ValueError("courses must contain at least one course")
    for course in courses:
        if not isinstance(course, dict) or not all(
            isinstance(course.get(key), str) and course[key] and "REPLACE" not in course[key]
            for key in ("kcid", "jx0404id")
        ):
            raise ValueError("each course needs its own kcid and jx0404id")

    for key in ("min_interval_seconds", "max_attempts", "timeout_seconds"):
        if not isinstance(config.get(key), (int, float)) or config[key] <= 0:
            raise ValueError(f"{key} must be a positive number")
    if int(config["max_attempts"]) != config["max_attempts"]:
        raise ValueError("max_attempts must be an integer")
    delay = config.get("retry_delay_seconds")
    if not isinstance(delay, list) or len(delay) != 2 or not all(isinstance(x, (int, float)) for x in delay) or delay[0] < 0 or delay[1] < delay[0]:
        raise ValueError("retry_delay_seconds must be [minimum, maximum]")
    return config


class RequestLimiter:
    def __init__(self, min_interval):
        self.min_interval = min_interval
        self.last_request = 0.0
        self.lock = threading.Lock()

    def wait(self, stop_event):
        with self.lock:
            remaining = self.min_interval - (time.monotonic() - self.last_request)
            if remaining > 0 and stop_event.wait(remaining):
                return False
            if stop_event.is_set():
                return False
            self.last_request = time.monotonic()
            return True


def response_result(response):
    """Return (success, message) without logging response bodies or cookies."""
    try:
        payload = response.json()
    except ValueError:
        return False, "non-JSON response"
    if not isinstance(payload, dict):
        return False, "unexpected response format"
    result = payload.get("success")
    if isinstance(result, list) and len(result) >= 2 and result[1]:
        return True, "course selected"
    return False, str(payload.get("message") or "course not selected")


def select_course(course, config, limiter, stop_event):
    import requests

    label = course["kcid"][:8] + "…"
    params = {
        "kcid": course["kcid"],
        "cfbs": "null",
        "jx0404id": course["jx0404id"],
        "xkzy": "",
        "trjf": "",
    }
    headers = {
        "Accept": "*/*",
        "Referer": config["referer_url"],
        "User-Agent": config.get("user_agent", "Mozilla/5.0"),
        "X-Requested-With": "XMLHttpRequest",
    }

    for attempt in range(1, int(config["max_attempts"]) + 1):
        if not limiter.wait(stop_event):
            break
        try:
            response = requests.get(
                config["operation_url"],
                params=params,
                cookies=config["cookies"],
                headers=headers,
                timeout=config["timeout_seconds"],
            )
            if response.status_code in (401, 403):
                LOG.error("%s: authentication failed (HTTP %s); refresh cookies", label, response.status_code)
                return False
            if response.status_code == 200:
                success, message = response_result(response)
                if success:
                    LOG.info("%s: selected on attempt %s", label, attempt)
                    return True
                LOG.info("%s: attempt %s: %s", label, attempt, message)
            else:
                LOG.warning("%s: attempt %s: HTTP %s", label, attempt, response.status_code)
        except requests.RequestException as exc:
            LOG.warning("%s: attempt %s: %s", label, attempt, type(exc).__name__)

        if attempt < config["max_attempts"]:
            delay = random.uniform(*config["retry_delay_seconds"])
            if stop_event.wait(delay):
                break
    LOG.warning("%s: stopped without confirmation of selection", label)
    return False


def configure_logging():
    LOG.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    for handler in (logging.StreamHandler(), logging.FileHandler(ROOT / "logfile.txt", encoding="utf-8")):
        handler.setFormatter(formatter)
        LOG.addHandler(handler)


def main():
    parser = argparse.ArgumentParser(description="SDU course-selection retry script")
    parser.add_argument("--config", type=Path, default=ROOT / "config.json", help="local JSON configuration")
    parser.add_argument("--check", action="store_true", help="validate configuration without sending requests")
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        parser.exit(2, f"Configuration error: {exc}\nSee README.md and config.example.json.\n")

    if args.check:
        print(f"Configuration valid: {len(config['courses'])} course(s); endpoint: {config['operation_url']}")
        print("No network request was sent.")
        return

    try:
        import requests  # noqa: F401
    except ImportError:
        parser.exit(2, "Missing dependency: run python -m pip install -r requirements.txt\n")

    configure_logging()
    LOG.info("Starting %s course task(s); minimum interval: %ss", len(config["courses"]), config["min_interval_seconds"])
    limiter = RequestLimiter(config["min_interval_seconds"])
    stop_event = threading.Event()
    with ThreadPoolExecutor(max_workers=min(len(config["courses"]), 4)) as executor:
        futures = {
            executor.submit(select_course, course, config, limiter, stop_event): course["kcid"][:8] + "…"
            for course in config["courses"]
        }
        try:
            for future in as_completed(futures):
                LOG.info("%s: %s", futures[future], "success" if future.result() else "not selected")
        except KeyboardInterrupt:
            LOG.info("Interrupted by user; stopping after current requests")
            stop_event.set()


if __name__ == "__main__":
    main()

