#!/usr/bin/env python3
"""Icinga2/Nagios-style check plugin for the Graylog REST API.

Modes (--mode):
  lbstatus     Graylog's own load-balancer health flag (ALIVE/THROTTLED/DEAD)
  cluster      Indexer (Elasticsearch/OpenSearch) cluster health (green/yellow/red)
  journal      Message journal utilization -- the canary for "Graylog can't
               write to the indexer fast enough and is buffering to disk"
  inputs       Any configured input not in RUNNING state
  throughput   Cluster-wide messages/sec, optionally thresholded as a floor
  nodes        Every Graylog node's own reported health (GET /cluster) --
               catches a node missing entirely or reporting itself unhealthy,
               which lbstatus/cluster/journal (all answered by whichever node
               the request happens to hit) can't see
  metric       One named Dropwizard metric (JVM heap, GC, buffers, pipeline
               performance, ...), fetched generically -- see list-metrics
  list-metrics Discovery helper: list available metric names (optionally
               filtered), not a real check -- always exits OK

Auth: Graylog REST API tokens are used as HTTP Basic Auth, with the token as
the username and the literal string "token" as the password. Create one
under a low-privilege ("Reader") Graylog user for monitoring, not an admin
account -- see README.md.
"""

import argparse
import sys

import requests

OK, WARNING, CRITICAL, UNKNOWN = 0, 1, 2, 3
STATUS_NAMES = {OK: "OK", WARNING: "WARNING", CRITICAL: "CRITICAL", UNKNOWN: "UNKNOWN"}


def parse_args():
    p = argparse.ArgumentParser(description="Check Graylog health via its REST API")
    p.add_argument("--url", required=True, help="Graylog API root, e.g. https://graylog.home.arpa:9000/api")
    p.add_argument("--token", required=True, help="Graylog API token")
    p.add_argument(
        "--mode",
        required=True,
        choices=["lbstatus", "cluster", "journal", "inputs", "throughput", "nodes", "metric", "list-metrics"],
    )
    p.add_argument("--warning", type=float, help="Warning threshold (meaning depends on --mode)")
    p.add_argument("--critical", type=float, help="Critical threshold (meaning depends on --mode)")
    p.add_argument("--timeout", type=float, default=10, help="HTTP timeout in seconds (default: 10)")
    p.add_argument("--insecure", action="store_true", help="Skip TLS certificate verification")
    p.add_argument("--expected-nodes", type=int, help="--mode nodes: CRITICAL if fewer nodes than this respond")
    p.add_argument("--metric-name", help="--mode metric: exact Dropwizard metric name, e.g. jvm.memory.heap.usage")
    p.add_argument(
        "--field",
        default="value",
        help="--mode metric: JSON key (dotted path) inside the metric object to threshold on (default: value)",
    )
    p.add_argument("--filter", help="--mode list-metrics: only show names containing this substring")
    args = p.parse_args()

    if args.mode == "metric" and not args.metric_name:
        p.error("--mode metric requires --metric-name (use --mode list-metrics to find one)")
    return args


def api_get(base_url, token, path, timeout, verify):
    url = base_url.rstrip("/") + path
    try:
        resp = requests.get(
            url,
            auth=(token, "token"),
            headers={"Accept": "application/json", "X-Requested-By": "icinga2-check_graylog"},
            timeout=timeout,
            verify=verify,
        )
    except requests.exceptions.RequestException as exc:
        die(UNKNOWN, f"could not reach {url}: {exc}")
    if resp.status_code != 200:
        die(UNKNOWN, f"{url} returned HTTP {resp.status_code}: {resp.text[:200]}")
    return resp


def die(code, message, perfdata=None):
    line = f"GRAYLOG {STATUS_NAMES[code]} - {message}"
    if perfdata:
        line += " | " + " ".join(perfdata)
    print(line)
    sys.exit(code)


def check_lbstatus(args, verify):
    # Unlike every other endpoint here, /system/lbstatus signals state via
    # the HTTP status code itself (200=ALIVE, 429=THROTTLED, 503=DEAD), not
    # via the response body -- confirmed against Graylog 7.1.3's OpenAPI
    # spec. Can't go through api_get(), which treats non-200 as UNKNOWN.
    #
    # Also: this endpoint replies text/plain, not JSON -- confirmed live
    # against Graylog 6.1. Requesting "Accept: application/json" (like every
    # other endpoint here) makes it return 406 Not Acceptable instead of the
    # actual ALIVE/THROTTLED/DEAD status.
    url = args.url.rstrip("/") + "/system/lbstatus"
    try:
        resp = requests.get(
            url,
            auth=(args.token, "token"),
            headers={"Accept": "*/*", "X-Requested-By": "icinga2-check_graylog"},
            timeout=args.timeout,
            verify=verify,
        )
    except requests.exceptions.RequestException as exc:
        die(UNKNOWN, f"could not reach {url}: {exc}")

    mapping = {200: ("ALIVE", OK), 429: ("THROTTLED", WARNING), 503: ("DEAD", CRITICAL)}
    status, code = mapping.get(resp.status_code, (f"HTTP {resp.status_code}", UNKNOWN))
    die(code, f"load balancer status is {status}")


def check_cluster(args, verify):
    resp = api_get(args.url, args.token, "/system/indexer/cluster/health", args.timeout, verify)
    data = resp.json()
    status = str(data.get("status", "unknown")).lower()
    mapping = {"green": OK, "yellow": WARNING, "red": CRITICAL}
    code = mapping.get(status, UNKNOWN)

    shards = data.get("shards", {})
    perf = []
    for key in ("active", "initializing", "relocating", "unassigned"):
        if key in shards:
            perf.append(f"shards_{key}={shards[key]};;;0")

    die(code, f"indexer cluster health is {status}", perf)


def check_journal(args, verify):
    resp = api_get(args.url, args.token, "/system/journal", args.timeout, verify)
    data = resp.json()

    if not data.get("enabled", True):
        die(OK, "journal is disabled (messages go straight to the indexer)")

    # No utilization_ratio field in Graylog's JournalSummaryResponse (checked
    # against the 7.1.3 OpenAPI spec) -- only journal_size and
    # journal_size_limit are reported, so utilization has to be derived.
    size = data.get("journal_size", 0)
    size_limit = data.get("journal_size_limit", 0)
    utilization_pct = round(size / size_limit * 100, 1) if size_limit else 0.0
    uncommitted = data.get("uncommitted_journal_entries", 0)
    read_rate = data.get("read_events_per_second", 0)
    write_rate = data.get("append_events_per_second", 0)

    warn = args.warning if args.warning is not None else 80.0
    crit = args.critical if args.critical is not None else 95.0

    if utilization_pct >= crit:
        code = CRITICAL
    elif utilization_pct >= warn:
        code = WARNING
    else:
        code = OK

    perf = [
        f"utilization={utilization_pct}%;{warn};{crit};0;100",
        f"uncommitted_entries={uncommitted};;;0",
        f"read_msgs_per_sec={read_rate};;;0",
        f"write_msgs_per_sec={write_rate};;;0",
    ]
    die(code, f"journal utilization is {utilization_pct}% ({uncommitted} uncommitted entries)", perf)


def check_inputs(args, verify):
    resp = api_get(args.url, args.token, "/system/inputstates", args.timeout, verify)
    states = resp.json().get("states", [])

    total = len(states)
    not_running = [
        s.get("message_input", {}).get("title", s.get("id", "?")) + f" ({s.get('state')})"
        for s in states
        if s.get("state") != "RUNNING"
    ]
    running = total - len(not_running)

    perf = [f"total={total};;;0", f"running={running};;;0", f"failed={len(not_running)};;;0"]

    if not total:
        die(WARNING, "no inputs configured", perf)
    if not_running:
        die(CRITICAL, f"{len(not_running)}/{total} input(s) not running: {', '.join(not_running)}", perf)
    die(OK, f"all {total} input(s) running", perf)


def check_throughput(args, verify):
    resp = api_get(args.url, args.token, "/system/throughput", args.timeout, verify)
    throughput = resp.json().get("throughput", 0)

    perf = [f"throughput={throughput};{args.warning or ''};{args.critical or ''};0"]

    # Thresholds here are a floor: throughput dropping *below* the value is
    # the problem (ingestion stalled), not exceeding it.
    if args.critical is not None and throughput < args.critical:
        die(CRITICAL, f"throughput is {throughput} msg/s (below critical floor {args.critical})", perf)
    if args.warning is not None and throughput < args.warning:
        die(WARNING, f"throughput is {throughput} msg/s (below warning floor {args.warning})", perf)
    die(OK, f"throughput is {throughput} msg/s", perf)


def check_nodes(args, verify):
    # GET /cluster -- confirmed against the 7.1.3 OpenAPI spec: a dict of
    # node_id -> SystemOverviewResponse (hostname, is_processing, lb_status,
    # lifecycle, ...). Answers "are all Graylog nodes reachable", which
    # lbstatus/cluster/journal can't -- those are all answered by whichever
    # single node the request happens to hit, not the whole cluster.
    resp = api_get(args.url, args.token, "/cluster", args.timeout, verify)
    nodes = resp.json()
    total = len(nodes)

    unhealthy = []
    for node_id, info in nodes.items():
        label = info.get("hostname", node_id)
        lb_status = str(info.get("lb_status", "")).upper()
        if lb_status != "ALIVE" or not info.get("is_processing", True):
            unhealthy.append(f"{label} (lb_status={lb_status or '?'}, is_processing={info.get('is_processing')})")

    perf = [f"total={total};;;0", f"unhealthy={len(unhealthy)};;;0"]

    if args.expected_nodes and total < args.expected_nodes:
        die(CRITICAL, f"only {total}/{args.expected_nodes} expected node(s) responded", perf)
    if unhealthy:
        die(CRITICAL, f"{len(unhealthy)}/{total} node(s) unhealthy: {', '.join(unhealthy)}", perf)
    if not total:
        die(UNKNOWN, "no nodes reported by /cluster", perf)
    die(OK, f"all {total} node(s) healthy", perf)


def _extract_metric_value(metric_json, field):
    # Dropwizard/Codahale metrics serialize differently per type (Gauge:
    # {"value": ...}, Counter: {"count": ...}, Meter/Timer: nested rate/time
    # objects) -- the OpenAPI spec leaves this schema empty (untyped), so
    # this is a best-effort walk of a dotted --field path, not a verified
    # contract. Confirm the real shape with --mode list-metrics + a manual
    # GET against the live instance before trusting thresholds on it.
    value = metric_json
    for part in field.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def check_metric(args, verify):
    resp = api_get(args.url, args.token, f"/system/metrics/{args.metric_name}", args.timeout, verify)
    data = resp.json()

    value = _extract_metric_value(data, args.field)
    if value is None:
        die(UNKNOWN, f"metric '{args.metric_name}' has no field '{args.field}' in {data}")
    if not isinstance(value, (int, float)):
        die(OK, f"{args.metric_name} = {value}")

    warn, crit = args.warning, args.critical
    if crit is not None and value >= crit:
        code = CRITICAL
    elif warn is not None and value >= warn:
        code = WARNING
    else:
        code = OK

    perf = [f"{args.metric_name.replace('.', '_')}={value};{warn or ''};{crit or ''}"]
    die(code, f"{args.metric_name} ({args.field}) = {value}", perf)


def check_list_metrics(args, verify):
    resp = api_get(args.url, args.token, "/system/metrics/names", args.timeout, verify)
    names = sorted(resp.json().get("names", []))
    if args.filter:
        names = [n for n in names if args.filter in n]
    die(OK, f"{len(names)} metric name(s)" + (f" matching '{args.filter}'" if args.filter else "") + ":\n" + "\n".join(names))


def main():
    args = parse_args()
    verify = not args.insecure

    checks = {
        "lbstatus": check_lbstatus,
        "cluster": check_cluster,
        "journal": check_journal,
        "inputs": check_inputs,
        "throughput": check_throughput,
        "nodes": check_nodes,
        "metric": check_metric,
        "list-metrics": check_list_metrics,
    }
    checks[args.mode](args, verify)


if __name__ == "__main__":
    main()
