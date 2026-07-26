#!/usr/bin/env python3
"""Zabbix-native Graylog check -- one raw value per invocation, no OK/WARNING/
CRITICAL logic baked in. Threshold evaluation belongs in Zabbix triggers, not
here -- that's the idiomatic Zabbix model (item = raw value, trigger =
expression against that value), unlike the Nagios/Icinga2 plugin API this
was originally built for (see ../../icinga/plugins/check_graylog.py).

Auth, endpoints, and JSON field names are identical to the Icinga2 variant --
that half was already verified live against a real Graylog instance. Only
the *output shape* differs here.

Modes (--mode), each prints exactly one value to stdout and exits 0 on
success, 1 on any error (unreachable, bad auth, missing field):
  lbstatus                 -> string: ALIVE / THROTTLED / DEAD
  cluster-status            -> string: green / yellow / red
  cluster-shards-unassigned -> integer
  journal-utilization       -> float, percent (0-100)
  journal-uncommitted       -> integer
  journal-read-rate         -> number, msgs/sec
  journal-write-rate        -> number, msgs/sec
  inputs-total              -> integer
  inputs-running            -> integer
  inputs-failed             -> integer
  throughput                -> integer, msgs/sec
  nodes-total               -> integer
  nodes-unhealthy           -> integer
  metric                    -> passthrough for any Dropwizard metric (needs --metric-name, --field)
  list-metrics-lld          -> Zabbix Low-Level Discovery JSON (for building item prototypes)

Auth: same as the Icinga2 variant -- Graylog API token as the Basic Auth
username, literal string "token" as password.
"""

import argparse
import json
import sys

import requests


def parse_args():
    p = argparse.ArgumentParser(description="Zabbix-native Graylog check (raw values, no thresholds)")
    p.add_argument("--url", required=True, help="Graylog API root, e.g. https://graylog.home.arpa:9000/api")
    p.add_argument("--token", required=True, help="Graylog API token")
    p.add_argument(
        "--mode",
        required=True,
        choices=[
            "lbstatus",
            "cluster-status",
            "cluster-shards-unassigned",
            "journal-utilization",
            "journal-uncommitted",
            "journal-read-rate",
            "journal-write-rate",
            "inputs-total",
            "inputs-running",
            "inputs-failed",
            "throughput",
            "nodes-total",
            "nodes-unhealthy",
            "metric",
            "list-metrics-lld",
        ],
    )
    p.add_argument("--timeout", type=float, default=10, help="HTTP timeout in seconds (default: 10)")
    p.add_argument("--insecure", action="store_true", help="Skip TLS certificate verification")
    p.add_argument("--metric-name", help="--mode metric / list-metrics-lld: exact or filter metric name")
    p.add_argument("--field", default="value", help="--mode metric: JSON key inside the metric object (default: value)")
    args = p.parse_args()
    if args.mode == "metric" and not args.metric_name:
        p.error("--mode metric requires --metric-name")
    return args


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def api_get(base_url, token, path, timeout, verify, accept="application/json"):
    url = base_url.rstrip("/") + path
    try:
        resp = requests.get(
            url,
            auth=(token, "token"),
            headers={"Accept": accept, "X-Requested-By": "zabbix-check_graylog"},
            timeout=timeout,
            verify=verify,
        )
    except requests.exceptions.RequestException as exc:
        fail(f"could not reach {url}: {exc}")
    if resp.status_code != 200:
        fail(f"{url} returned HTTP {resp.status_code}: {resp.text[:200]}")
    return resp


def cmd_lbstatus(args, verify):
    # Same quirk as the Icinga2 variant: status is the HTTP status code
    # itself (200/429/503), and the endpoint replies text/plain -- Accept:
    # application/json makes Graylog return 406. Confirmed live 2026-07-24.
    url = args.url.rstrip("/") + "/system/lbstatus"
    try:
        resp = requests.get(
            url,
            auth=(args.token, "token"),
            headers={"Accept": "*/*", "X-Requested-By": "zabbix-check_graylog"},
            timeout=args.timeout,
            verify=verify,
        )
    except requests.exceptions.RequestException as exc:
        fail(f"could not reach {url}: {exc}")
    mapping = {200: "ALIVE", 429: "THROTTLED", 503: "DEAD"}
    print(mapping.get(resp.status_code, f"UNKNOWN_HTTP_{resp.status_code}"))


def cmd_cluster_status(args, verify):
    data = api_get(args.url, args.token, "/system/indexer/cluster/health", args.timeout, verify).json()
    print(str(data.get("status", "unknown")).lower())


def cmd_cluster_shards_unassigned(args, verify):
    data = api_get(args.url, args.token, "/system/indexer/cluster/health", args.timeout, verify).json()
    print(data.get("shards", {}).get("unassigned", 0))


def cmd_journal(args, verify, field):
    data = api_get(args.url, args.token, "/system/journal", args.timeout, verify).json()
    if field == "utilization":
        size = data.get("journal_size", 0)
        limit = data.get("journal_size_limit", 0)
        pct = round(size / limit * 100, 2) if limit else 0.0
        print(pct)
    elif field == "uncommitted":
        print(data.get("uncommitted_journal_entries", 0))
    elif field == "read-rate":
        print(data.get("read_events_per_second", 0))
    elif field == "write-rate":
        print(data.get("append_events_per_second", 0))


def cmd_inputs(args, verify, field):
    states = api_get(args.url, args.token, "/system/inputstates", args.timeout, verify).json().get("states", [])
    total = len(states)
    running = sum(1 for s in states if s.get("state") == "RUNNING")
    if field == "total":
        print(total)
    elif field == "running":
        print(running)
    elif field == "failed":
        print(total - running)


def cmd_throughput(args, verify):
    data = api_get(args.url, args.token, "/system/throughput", args.timeout, verify).json()
    print(data.get("throughput", 0))


def cmd_nodes(args, verify, field):
    nodes = api_get(args.url, args.token, "/cluster", args.timeout, verify).json()
    total = len(nodes)
    unhealthy = sum(
        1
        for info in nodes.values()
        if str(info.get("lb_status", "")).upper() != "ALIVE" or not info.get("is_processing", True)
    )
    print(total if field == "total" else unhealthy)


def cmd_metric(args, verify):
    data = api_get(args.url, args.token, f"/system/metrics/{args.metric_name}", args.timeout, verify).json()
    value = data
    for part in args.field.split("."):
        if not isinstance(value, dict) or part not in value:
            fail(f"metric '{args.metric_name}' has no field '{args.field}' in {data}")
        value = value[part]
    print(value)


def cmd_list_metrics_lld(args, verify):
    names = api_get(args.url, args.token, "/system/metrics/names", args.timeout, verify).json().get("names", [])
    if args.metric_name:
        names = [n for n in names if args.metric_name in n]
    lld = {"data": [{"{#METRICNAME}": n} for n in sorted(names)]}
    print(json.dumps(lld))


def main():
    args = parse_args()
    verify = not args.insecure

    dispatch = {
        "lbstatus": lambda: cmd_lbstatus(args, verify),
        "cluster-status": lambda: cmd_cluster_status(args, verify),
        "cluster-shards-unassigned": lambda: cmd_cluster_shards_unassigned(args, verify),
        "journal-utilization": lambda: cmd_journal(args, verify, "utilization"),
        "journal-uncommitted": lambda: cmd_journal(args, verify, "uncommitted"),
        "journal-read-rate": lambda: cmd_journal(args, verify, "read-rate"),
        "journal-write-rate": lambda: cmd_journal(args, verify, "write-rate"),
        "inputs-total": lambda: cmd_inputs(args, verify, "total"),
        "inputs-running": lambda: cmd_inputs(args, verify, "running"),
        "inputs-failed": lambda: cmd_inputs(args, verify, "failed"),
        "throughput": lambda: cmd_throughput(args, verify),
        "nodes-total": lambda: cmd_nodes(args, verify, "total"),
        "nodes-unhealthy": lambda: cmd_nodes(args, verify, "unhealthy"),
        "metric": lambda: cmd_metric(args, verify),
        "list-metrics-lld": lambda: cmd_list_metrics_lld(args, verify),
    }
    dispatch[args.mode]()


if __name__ == "__main__":
    main()
