# P0 monitoring deployment

Use matching `codex/observability-p0` source branches of DingoFS, dingocli and
ansible-dingofs. This phase reuses bRPC `/brpc_metrics` and existing deployment;
P1 request histograms, business error classification and measured Data Flow are
not enabled by these changes.

The monitor role's default host list is the deduplicated union of `meta_servers`,
`cache_servers` and `client_servers`. An explicit override must cover those groups.
All hosts must already be registered in `dingo hosts`. The paired CLI uses the
explicit monitoring host list instead of just the metadata deployment topology,
resolves each host to its configured address, and produces node targets with
stable `cluster/node/component=host` labels. Unknown or ambiguous host identities
are rejected. Central services have explicit `deploy` entries.

To apply reviewed source assets to a new or existing monitor stack, configure:

```yaml
dingo_monitor_observability_assets_dir: /absolute/path/to/dingofs/scripts/monitor
dingo_monitor_discovery_interval: 60
dingo_monitor_discovery_retention_seconds: 3600
dingo_monitor_discovery_metrics_port: 19100
dingo_monitor_expected_targets:
  - targets: ["192.0.2.10:7801"]
    labels: {cluster: my-cluster, component: mds, node: meta-1}
  - targets: ["192.0.2.20:10000"]
    labels: {cluster: my-cluster, component: client, node: worker-1, fs_id: "42"}
  - targets: ["192.0.2.20:9300"]
    labels: {cluster: my-cluster, component: cache, node: worker-1}
```

The cluster value must equal `dingofs_cluster_name`. The expected list is
operator-maintained and independent of dynamic discovery; do not derive it from
a failed or successful discovery result. Use the same node identity for host
scrapes and application endpoints. Include all expected mounts, with distinct
ports even on the same host. Inventory changes restart discovery. Retired targets
must be explicitly removed; silence approved maintenance in Alertmanager.

```bash
ansible-playbook -i inventory/hosts.yml playbooks/06_deploy_monitor.yml
```

The source overlay is opt-in through `dingo_monitor_observability_assets_dir`.
It stages inventory and Prometheus/rules validation before changing live files,
then installs the cluster/port configuration and reviewed dashboards. It restarts
only the affected monitoring services. It preserves TSDB state, discovery state
and the legacy dashboards. Ordinary role check mode skips the asset application.

An unset expected-inventory variable preserves the existing file. On first
installation it starts empty; explicitly setting [] retires all expected targets.
An empty inventory does not provide removal coverage. Review
actual MDS/client/cache endpoints, node coverage, discovery freshness thresholds,
retention and alert routing before release. Re-running the existing deploy step
alone does not recreate a monitor stack; this overlay handles configuration
updates separately after the role's existing registration/status checks.

Validation:

```bash
python -m unittest discover -s tests -p test_monitor_observability.py -v
python -m unittest discover -s tests -p test_issue_triage.py -v
ansible-playbook playbooks/06_deploy_monitor.yml --syntax-check
```

Fixture tests exercise actual Ansible task execution with isolated fake services:
failed validation leaves live configuration untouched, wrong-cluster inventory
fails before writes, and a second identical run does not restart services.
See DingoFS `scripts/monitor/P0.md` for source/type contracts and runtime evidence
collection. Static tests alone do not prove DingoFS runtime acceptance.
