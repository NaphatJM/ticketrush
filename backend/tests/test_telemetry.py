import json
import logging
import os
import runpy
import subprocess  # noqa: S404
import sys
import threading
import weakref
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import pytest
from celery.signals import beat_init
from celery.signals import worker_process_init
from celery.signals import worker_process_shutdown
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider

from ticketrush import celery as celery_module
from ticketrush import system_metrics
from ticketrush import telemetry
from utils.log_formatters import JsonFormatter


BACKEND = Path(__file__).resolve().parent.parent

EXPORT_SCRIPT = """
import logging
import runpy
from wsgiref.util import setup_testing_defaults

# Same order as a gunicorn worker: post_fork, then the WSGI app loads Django and its logging config.
runpy.run_path('gunicorn.conf.py')['post_fork'](server=None, worker=None)

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()

from django_guid import set_guid
from opentelemetry import metrics
from opentelemetry import trace

from ticketrush import telemetry

for path in ('/system/healthcheck/', '/system/schema/'):
    environ = {'PATH_INFO': path}
    setup_testing_defaults(environ)
    b''.join(application(environ, lambda status, headers: None))

otel_logger = logging.getLogger('opentelemetry.exporter.otlp.proto.http.trace_exporter')
assert not otel_logger.disabled
assert [handler.name for handler in logging.getLogger('opentelemetry').handlers] == ['console']

set_guid('cid-export-test')
with trace.get_tracer('export-test').start_as_current_span('export-test-span'):
    logging.getLogger('ticketing').warning('export test line')
metrics.get_meter('export-test').create_counter('export_test.counter').add(1)
telemetry.shutdown()
"""


class _Collector(BaseHTTPRequestHandler):
    received: list[tuple[str, dict, bytes]]

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers['Content-Length']))
        self.received.append((self.path, {key.lower(): value for key, value in self.headers.items()}, body))
        self.send_response(200)
        self.send_header('Content-Length', '0')
        self.end_headers()

    def log_message(self, format, *args):  # noqa: A002
        pass


@pytest.fixture
def collector():
    handler = type('Collector', (_Collector,), {'received': []})
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, handler.received
    server.shutdown()
    server.server_close()


def _attributes(key_values) -> dict:
    return {kv.key: kv.value.string_value for kv in key_values}


def test_configure_does_nothing_without_an_endpoint(monkeypatch):
    monkeypatch.delenv('OTEL_EXPORTER_OTLP_ENDPOINT', raising=False)

    with mock.patch.object(telemetry.trace, 'set_tracer_provider') as set_tracer_provider:
        assert telemetry.configure() is False

    set_tracer_provider.assert_not_called()


def test_a_configured_worker_exports_traces_logs_and_metrics(collector):
    server, received = collector
    inherited = {key: value for key, value in os.environ.items() if not key.startswith('OTEL_') and 'PROXY' not in key.upper()}
    env = inherited | {
        'DJANGO_SETTINGS_MODULE': 'ticketrush.settings.test',
        'OTEL_EXPORTER_OTLP_ENDPOINT': f'http://127.0.0.1:{server.server_address[1]}',
        'OTEL_EXPORTER_OTLP_HEADERS': 'Authorization=Basic%20dGVzdA==',
        'OTEL_SERVICE_NAME': 'ticketrush-export-test',
    }

    subprocess.run([sys.executable, '-c', EXPORT_SCRIPT], cwd=BACKEND, env=env, check=True, timeout=60)  # noqa: S603

    assert {'/v1/traces', '/v1/logs', '/v1/metrics'} <= {path for path, _, _ in received}
    assert all(headers['authorization'] == 'Basic dGVzdA==' for _, headers, _ in received)

    traces = [ExportTraceServiceRequest.FromString(body) for path, _, body in received if path == '/v1/traces']
    resource = _attributes(traces[0].resource_spans[0].resource.attributes)
    assert resource['service.name'] == 'ticketrush-export-test'
    assert resource['deployment.environment.name']
    assert resource['service.instance.id']
    spans = [span for request in traces for rs in request.resource_spans for ss in rs.scope_spans for span in ss.spans]
    [span] = [span for span in spans if span.name == 'export-test-span']
    [server_span] = [span for span in spans if span.kind == span.SPAN_KIND_SERVER]
    server_attributes = _attributes(server_span.attributes)
    assert server_attributes['http.route'] == 'system/schema/'
    assert server_attributes['cid']

    logs = [ExportLogsServiceRequest.FromString(body) for path, _, body in received if path == '/v1/logs']
    records = [r for request in logs for rl in request.resource_logs for sl in rl.scope_logs for r in sl.log_records]
    [record] = [r for r in records if r.body.string_value == 'export test line']
    assert _attributes(record.attributes)['correlation_id'] == 'cid-export-test'
    assert record.trace_id == span.trace_id

    exported = [ExportMetricsServiceRequest.FromString(body) for path, _, body in received if path == '/v1/metrics']
    metrics_by_name = {
        metric.name: metric for request in exported for rm in request.resource_metrics for sm in rm.scope_metrics for metric in sm.metrics
    }
    assert 'export_test.counter' in metrics_by_name
    [duration] = metrics_by_name['http.server.request.duration'].histogram.data_points
    assert {kv.key for kv in duration.attributes} <= {'http.request.method', 'http.response.status_code', 'http.route', 'error.type'}
    assert list(duration.explicit_bounds) == list(telemetry.HTTP_DURATION_BUCKETS_SECONDS)


def test_json_lines_carry_the_active_trace():
    tracer = TracerProvider().get_tracer('test')
    record = logging.LogRecord('ticketrush.test', logging.INFO, __file__, 10, 'inside a span', (), None)

    with tracer.start_as_current_span('request') as span:
        line = json.loads(JsonFormatter().format(record))

    context = span.get_span_context()
    assert line['trace_id'] == f'{context.trace_id:032x}'
    assert line['span_id'] == f'{context.span_id:016x}'


def test_json_lines_outside_a_span_have_no_trace():
    record = logging.LogRecord('ticketrush.test', logging.INFO, __file__, 10, 'no span', (), None)

    line = json.loads(JsonFormatter().format(record))

    assert 'trace_id' not in line


def test_gunicorn_starts_telemetry_in_each_forked_worker():
    config = runpy.run_path(str(BACKEND / 'gunicorn.conf.py'))

    with mock.patch.object(telemetry, 'configure') as configure:
        config['post_fork'](server=None, worker=None)

    configure.assert_called_once_with()
    # A preloaded app would import Django, and start any exporter it touches, in the master before fork.
    assert not config.get('preload_app')


def _receivers(signal) -> list:
    return [ref() if isinstance(ref, weakref.ref) else ref for _, ref in signal.receivers]


def test_celery_starts_telemetry_in_each_pool_process_and_flushes_on_exit():
    assert celery_module.start_worker_telemetry in _receivers(worker_process_init)
    assert celery_module.flush_worker_telemetry in _receivers(worker_process_shutdown)
    assert celery_module.start_beat_telemetry in _receivers(beat_init)


def test_beat_registers_system_gauges_only_when_telemetry_is_on():
    with mock.patch.object(telemetry, 'configure', return_value=True), mock.patch.object(system_metrics, 'register') as register:
        celery_module.start_beat_telemetry()
    register.assert_called_once_with()

    with mock.patch.object(telemetry, 'configure', return_value=False), mock.patch.object(system_metrics, 'register') as register:
        celery_module.start_beat_telemetry()
    register.assert_not_called()


@pytest.mark.django_db
def test_system_gauges_are_collected():
    reader = InMemoryMetricReader()
    meter = MeterProvider(metric_readers=[reader]).get_meter('test')

    with (
        mock.patch.object(system_metrics.metrics, 'get_meter', return_value=meter),
        mock.patch.object(system_metrics, '_broker') as broker,
        mock.patch.object(system_metrics, 'close_old_connections'),
        mock.patch.object(system_metrics.before_task_publish, 'connect') as connect,
    ):
        broker.return_value.llen.return_value = 0
        system_metrics.register()
        data = reader.get_metrics_data()

    names = {metric.name for rm in data.resource_metrics for sm in rm.scope_metrics for metric in sm.metrics}
    assert {
        'ticketrush.beat.publish_age',
        'ticketrush.celery.queue.length',
        'ticketrush.outbox.unpublished',
        'ticketrush.outbox.oldest_age',
        'ticketrush.dead_letters.pending',
        'ticketrush.webhooks.unprocessed',
    } <= names
    connect.assert_called_once_with(system_metrics._mark_publish, weak=False)
