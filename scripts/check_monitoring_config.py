#!/usr/bin/env python3
"""Validate Skillra Prometheus rules and Grafana dashboard contracts."""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - exercised only in under-provisioned envs
    raise SystemExit("PyYAML is required: run make bootstrap-ci or install requirements/lock/dev.lock.txt") from exc


REQUIRED_ALERTS = {
    "SkillraPipelineLastSuccessTooOld",
    "SkillraPostgresBackupMissingOrStale",
    "SkillraPostgresRestoreDrillMissingOrStale",
    "DataStoreReloadLastRunFailed",
    "DataStoreReloadRedisPublishFailures",
    "VacancyIndexerLastRunFailed",
    "VacancyIndexerNoRecentSuccess",
    "EvidenceExplainerHighGuardrailRate",
    "EvidenceExplainerUnexpectedProdUse",
    "DigestWorkerInactive",
    "DigestWorkerNoClaims",
    "DigestWorkerSendFailures",
    "DigestWorkerAckFailures",
    "NoDigestsSentToday",
    "MeiliSearchDown",
}

REQUIRED_DASHBOARD_METRICS = {
    "skillra_pipeline_last_success_timestamp_seconds",
    "skillra_pg_backup_last_success_timestamp_seconds",
    "skillra_pg_restore_drill_last_success_timestamp_seconds",
    "skillra_vacancy_indexer_last_success_timestamp_seconds",
    "skillra_vacancy_indexer_failures_total",
    "skillra_product_events_total",
    "skillra_career_actions_total",
    "skillra_application_outcomes_total",
}

KNOWN_SKILLRA_METRICS = {
    "skillra_active_subscriptions",
    "skillra_api_request_errors_total",
    "skillra_api_request_latency_seconds",
    "skillra_api_request_latency_seconds_bucket",
    "skillra_api_request_latency_seconds_count",
    "skillra_api_request_latency_seconds_sum",
    "skillra_application_outcomes_total",
    "skillra_career_actions_total",
    "skillra_data_run_last_failure_timestamp_seconds",
    "skillra_data_run_last_success_timestamp_seconds",
    "skillra_data_run_processed_rows_total",
    "skillra_data_run_raw_rows_total",
    "skillra_data_run_state",
    "skillra_datastore_reload_failures_total",
    "skillra_datastore_reload_last_failure_timestamp_seconds",
    "skillra_datastore_reload_last_success_timestamp_seconds",
    "skillra_datastore_reload_redis_publish_failures_total",
    "skillra_datastore_reloads_total",
    "skillra_datastore_rows_total",
    "skillra_digest_worker_ack_failed_total",
    "skillra_digest_worker_claimed_total",
    "skillra_digest_worker_failed_total",
    "skillra_digest_worker_heartbeat_timestamp_seconds",
    "skillra_digest_worker_last_tick_timestamp_seconds",
    "skillra_digest_worker_sent_total",
    "skillra_digests_sent_total",
    "skillra_evidence_explainer_blocked_claims_total",
    "skillra_evidence_explainer_latency_seconds",
    "skillra_evidence_explainer_latency_seconds_bucket",
    "skillra_evidence_explainer_latency_seconds_count",
    "skillra_evidence_explainer_latency_seconds_sum",
    "skillra_evidence_explainer_requests_total",
    "skillra_persona_analyses_total",
    "skillra_pg_backup_last_retention_deleted_objects",
    "skillra_pg_backup_last_size_bytes",
    "skillra_pg_backup_last_success_timestamp_seconds",
    "skillra_pg_restore_drill_last_success_timestamp_seconds",
    "skillra_pg_restore_drill_restored_tables",
    "skillra_pipeline_last_success_timestamp_seconds",
    "skillra_product_events_total",
    "skillra_profiles_total",
    "skillra_vacancy_indexer_failures_total",
    "skillra_vacancy_indexer_last_failure_timestamp_seconds",
    "skillra_vacancy_indexer_last_indexed_total",
    "skillra_vacancy_indexer_last_success_timestamp_seconds",
}

SKILLRA_METRIC_RE = re.compile(r"\b(skillra_[a-zA-Z_:][a-zA-Z0-9_:]*)\b")


class MonitoringConfigError(RuntimeError):
    """Raised when the monitoring config contract is incomplete."""


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise MonitoringConfigError(f"{path}: expected YAML mapping")
    return payload


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise MonitoringConfigError(f"{path}: expected JSON object")
    return payload


def _prometheus_rule_patterns(prometheus_config: Path) -> list[str]:
    payload = _load_yaml(prometheus_config)
    rule_files = payload.get("rule_files")
    if not isinstance(rule_files, list) or not rule_files:
        raise MonitoringConfigError(f"{prometheus_config}: rule_files must be a non-empty list")

    patterns: list[str] = []
    for item in rule_files:
        if not isinstance(item, str) or not item.strip():
            raise MonitoringConfigError(f"{prometheus_config}: rule_files entries must be non-empty strings")
        patterns.append(item.strip())
    return patterns


def _validate_prometheus_scrape_jobs(prometheus_config: Path) -> None:
    payload = _load_yaml(prometheus_config)
    scrape_configs = payload.get("scrape_configs")
    if not isinstance(scrape_configs, list) or not scrape_configs:
        raise MonitoringConfigError(f"{prometheus_config}: scrape_configs must be a non-empty list")

    jobs = {job.get("job_name"): job for job in scrape_configs if isinstance(job, dict)}
    meili_job = jobs.get("meilisearch")
    if not isinstance(meili_job, dict):
        raise MonitoringConfigError(f"{prometheus_config}: meilisearch scrape job is required")

    authorization = meili_job.get("authorization")
    if not isinstance(authorization, dict):
        raise MonitoringConfigError(f"{prometheus_config}: meilisearch scrape job must define authorization")
    if authorization.get("type") != "Bearer":
        raise MonitoringConfigError(f"{prometheus_config}: meilisearch scrape job must use Bearer authorization")
    if authorization.get("credentials_file") != "/tmp/meilisearch_api_key":
        raise MonitoringConfigError(
            f"{prometheus_config}: meilisearch scrape job must use /tmp/meilisearch_api_key credentials_file"
        )


def _local_rule_glob(monitoring_dir: Path, prometheus_pattern: str) -> str:
    prefix = "/etc/prometheus/"
    if prometheus_pattern.startswith(prefix):
        return str(monitoring_dir / prometheus_pattern.removeprefix(prefix))
    return str(monitoring_dir / prometheus_pattern)


def _resolve_rule_files(monitoring_dir: Path, prometheus_config: Path) -> list[Path]:
    rule_files: list[Path] = []
    for pattern in _prometheus_rule_patterns(prometheus_config):
        local_pattern = _local_rule_glob(monitoring_dir, pattern)
        matches = sorted(Path(match) for match in glob.glob(local_pattern))
        if not matches:
            raise MonitoringConfigError(f"{prometheus_config}: rule_files pattern has no local matches: {pattern}")
        rule_files.extend(matches)

    unique_rule_files = sorted(set(rule_files))
    if not unique_rule_files:
        raise MonitoringConfigError(f"{prometheus_config}: no rule files resolved")
    return unique_rule_files


def _validate_alert_rule(rule_file: Path, group_name: str, rule: dict[str, Any], seen_alerts: set[str]) -> None:
    alert_name = rule.get("alert")
    if not isinstance(alert_name, str) or not alert_name:
        return
    if alert_name in seen_alerts:
        raise MonitoringConfigError(f"{rule_file}: duplicate alert name: {alert_name}")
    seen_alerts.add(alert_name)

    expr = rule.get("expr")
    if not isinstance(expr, str) or not expr.strip():
        raise MonitoringConfigError(f"{rule_file}: {alert_name} in {group_name} must define expr")
    _validate_known_skillra_metrics(expr, f"{rule_file}: {alert_name}")
    hold_for = rule.get("for")
    if not isinstance(hold_for, str) or not hold_for.strip():
        raise MonitoringConfigError(f"{rule_file}: {alert_name} in {group_name} must define for")

    labels = rule.get("labels")
    if not isinstance(labels, dict) or not isinstance(labels.get("severity"), str) or not labels["severity"]:
        raise MonitoringConfigError(f"{rule_file}: {alert_name} in {group_name} must define labels.severity")

    annotations = rule.get("annotations")
    if not isinstance(annotations, dict):
        raise MonitoringConfigError(f"{rule_file}: {alert_name} in {group_name} must define annotations")
    for field in ("summary", "description"):
        value = annotations.get(field)
        if not isinstance(value, str) or not value.strip():
            raise MonitoringConfigError(f"{rule_file}: {alert_name} in {group_name} must define annotations.{field}")


def _validate_rule_files(rule_files: list[Path]) -> set[str]:
    seen_alerts: set[str] = set()
    for rule_file in rule_files:
        payload = _load_yaml(rule_file)
        groups = payload.get("groups")
        if not isinstance(groups, list) or not groups:
            raise MonitoringConfigError(f"{rule_file}: groups must be a non-empty list")
        for group in groups:
            if not isinstance(group, dict):
                raise MonitoringConfigError(f"{rule_file}: every group must be a mapping")
            group_name = group.get("name")
            if not isinstance(group_name, str) or not group_name:
                raise MonitoringConfigError(f"{rule_file}: every group must define name")
            rules = group.get("rules")
            if not isinstance(rules, list) or not rules:
                raise MonitoringConfigError(f"{rule_file}: group {group_name} must define non-empty rules")
            for rule in rules:
                if not isinstance(rule, dict):
                    raise MonitoringConfigError(f"{rule_file}: group {group_name} has non-mapping rule")
                _validate_alert_rule(rule_file, group_name, rule, seen_alerts)

    missing_alerts = sorted(REQUIRED_ALERTS - seen_alerts)
    if missing_alerts:
        raise MonitoringConfigError("missing required alerts: " + ", ".join(missing_alerts))
    return seen_alerts


def _collect_dashboard_expressions(dashboard_dir: Path) -> list[str]:
    dashboard_files = sorted(dashboard_dir.glob("*.json"))
    if not dashboard_files:
        raise MonitoringConfigError(f"{dashboard_dir}: no dashboard JSON files found")

    expressions: list[str] = []
    for dashboard_file in dashboard_files:
        payload = _load_json(dashboard_file)
        title = payload.get("title")
        panels = payload.get("panels")
        if not isinstance(title, str) or not title:
            raise MonitoringConfigError(f"{dashboard_file}: dashboard title is required")
        if not isinstance(panels, list) or not panels:
            raise MonitoringConfigError(f"{dashboard_file}: panels must be a non-empty list")

        for panel in panels:
            if not isinstance(panel, dict):
                raise MonitoringConfigError(f"{dashboard_file}: every panel must be an object")
            panel_title = panel.get("title")
            if not isinstance(panel_title, str) or not panel_title:
                raise MonitoringConfigError(f"{dashboard_file}: every panel must define title")
            for target in panel.get("targets", []) or []:
                if isinstance(target, dict) and isinstance(target.get("expr"), str):
                    expr = target["expr"]
                    _validate_known_skillra_metrics(expr, f"{dashboard_file}: {panel_title}")
                    expressions.append(expr)
    return expressions


def _validate_known_skillra_metrics(expression: str, context: str) -> None:
    referenced = set(SKILLRA_METRIC_RE.findall(expression))
    unknown = sorted(referenced - KNOWN_SKILLRA_METRICS)
    if unknown:
        raise MonitoringConfigError(f"{context}: unknown Skillra metrics: " + ", ".join(unknown))


def _validate_dashboards(dashboard_dir: Path) -> None:
    expressions_text = "\n".join(_collect_dashboard_expressions(dashboard_dir))
    missing_metrics = sorted(metric for metric in REQUIRED_DASHBOARD_METRICS if metric not in expressions_text)
    if missing_metrics:
        raise MonitoringConfigError("missing dashboard metrics: " + ", ".join(missing_metrics))


def validate_monitoring_repo(repo_root: Path) -> None:
    root = repo_root.resolve()
    monitoring_dir = root / "infra" / "monitoring"
    prometheus_config = monitoring_dir / "prometheus.yml"
    dashboard_dir = monitoring_dir / "grafana" / "dashboards"

    _validate_prometheus_scrape_jobs(prometheus_config)
    rule_files = _resolve_rule_files(monitoring_dir, prometheus_config)
    _validate_rule_files(rule_files)
    _validate_dashboards(dashboard_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Skillra monitoring config contracts.")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root path")
    args = parser.parse_args(argv)

    try:
        validate_monitoring_repo(args.repo_root)
    except MonitoringConfigError as exc:
        print(f"monitoring config validation failed: {exc}", file=sys.stderr)
        return 1

    print("Monitoring config validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
