"""Exercise staged monitor updates without contacting any real service."""
import json
import os
from pathlib import Path
import pwd
import shlex
import shutil
import subprocess
import tempfile
import unittest

import yaml

REPO = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('ansible-playbook'), 'ansible-playbook is required')
class MonitorOverlayTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='monitor-overlay-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.assets, self.live = self.root/'assets', self.root/'live'
        for base in [self.assets, self.live]:
            for path in ['prometheus/data', 'prometheus/rules', 'grafana/provisioning/dashboards', 'grafana/provisioning/datasources']:
                (base/path).mkdir(parents=True)
        (self.assets/'target_json.py').write_text('def validate_groups(groups, cluster, expected=False):\n    assert isinstance(groups, list)\n    for g in groups:\n        assert g["labels"]["cluster"] == cluster\n')
        (self.assets/'prometheus/prometheus.yml').write_text('global: {}\nscrape_configs: []\n')
        (self.assets/'prometheus/rules/collection.yml').write_text('groups: []\n')
        (self.assets/'grafana/provisioning/dashboards/overview.json').write_text('{"uid":"p0"}\n')
        (self.assets/'grafana/provisioning/datasources/all.yml').write_text('url: http://localhost:9090\n')
        (self.live/'prometheus/prometheus.yml').write_text('original configuration\n')
        self.bin = self.root/'bin'
        self.bin.mkdir()
        self.log = self.root/'restarts.log'
        self.fail = self.root/'fail-validation'
        (self.bin/'engine').write_text('#!/bin/sh\nif [ -f '+shlex.quote(str(self.fail))+' ]; then exit 1; fi\n')
        (self.bin/'dingo').write_text('#!/bin/sh\nread answer\n[ "$answer" = yes ] || exit 1\nprintf "%s\\n" "$*" >> '+shlex.quote(str(self.log))+'\n')
        for path in self.bin.iterdir():
            path.chmod(0o755)
        self.vars = dict(ansible_become=False, dingofs_user=pwd.getpwuid(os.getuid()).pw_name,
                         dingo_monitor_central_host='localhost', dingofs_cluster_name='test',
                         dingo_monitor_observability_assets_dir=str(self.assets),
                         dingo_monitor_data_dir=str(self.live),
                         dingo_monitor_prometheus_port=29090, dingo_monitor_discovery_metrics_port=29101,
                         dingo_monitor_discovery_retention_seconds=120, dingo_monitor_discovery_interval=10,
                         dingo_monitor_prometheus_image='fixture/prometheus', container_engine=str(self.bin/'engine'),
                         dingo_cli_bin_dir=str(self.bin), dingo_monitor_expected_targets=[{
                             'targets':['host:7801'], 'labels':{'cluster':'test','component':'mds','node':'host'}}])

    def run_overlay(self):
        play = self.root/'play.yml'
        play.write_text(yaml.safe_dump([dict(hosts='localhost', gather_facts=False, vars=self.vars,
                                            tasks=[dict(include_role=dict(name='dingo_monitor', tasks_from='observability'))])]))
        env = dict(os.environ, ANSIBLE_ROLES_PATH=str(REPO/'roles'), ANSIBLE_NOCOLOR='1')
        return subprocess.run(['ansible-playbook','-i','localhost,','-c','local',str(play)],
                              capture_output=True, text=True, env=env)

    def test_validated_update_is_idempotent_and_cluster_scoped(self):
        first = self.run_overlay()
        self.assertEqual(first.returncode, 0, first.stdout+first.stderr)
        self.assertEqual(len(self.log.read_text().splitlines()), 3)
        self.assertIn('cluster=test', (self.live/'target.ini').read_text())
        self.assertIn('localhost:29090', (self.live/'grafana/provisioning/datasources/all.yml').read_text())
        # An omitted replacement must preserve the independent inventory.
        del self.vars['dingo_monitor_expected_targets']
        second = self.run_overlay()
        self.assertEqual(second.returncode, 0, second.stdout+second.stderr)
        self.assertEqual(len(self.log.read_text().splitlines()), 3, second.stdout)
        self.assertEqual(len(json.loads((self.live/'prometheus/expected-targets.json').read_text())), 1)

    def test_failed_validation_keeps_live_configuration_and_does_not_restart(self):
        self.fail.touch()
        result = self.run_overlay()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.live/'prometheus/prometheus.yml').read_text(), 'original configuration\n')
        self.assertFalse(self.log.exists())

    def test_wrong_cluster_inventory_fails_before_live_changes(self):
        self.vars['dingo_monitor_expected_targets'][0]['labels']['cluster'] = 'other'
        result = self.run_overlay()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.live/'prometheus/prometheus.yml').read_text(), 'original configuration\n')
        self.assertFalse(self.log.exists())


if __name__ == '__main__':
    unittest.main()
