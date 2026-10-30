"""OpenTelemetry export to an OTLP endpoint. Exporter threads do not survive fork, so each process calls `configure` after it forks."""

import os
import uuid

from django.conf import settings
from opentelemetry import metrics
from opentelemetry import trace
from opentelemetry._logs import get_logger_provider
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from opentelemetry.instrumentation.django import DjangoInstrumentor
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.urllib import URLLibInstrumentor
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.metrics.view import DropAggregation
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation
from opentelemetry.sdk.metrics.view import View
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


#: Platform probes arrive every few seconds and would bury real requests in traces.
EXCLUDED_URLS = 'system/healthcheck/,system/readiness/'

#: Per request; also bounds how long a worker's exit flush waits on an unreachable endpoint.
EXPORT_TIMEOUT_SECONDS = 5

#: Each boundary is one series per route, status, and process, against a 10k active-series quota.
HTTP_DURATION_BUCKETS_SECONDS = (0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5)

METRIC_VIEWS = (
    View(
        instrument_name='http.server.request.duration',
        attribute_keys={'http.request.method', 'http.response.status_code', 'http.route', 'error.type'},
        aggregation=ExplicitBucketHistogramAggregation(HTTP_DURATION_BUCKETS_SECONDS),
    ),
    # The Celery instrumentation's histogram uses millisecond buckets for seconds; task outcomes are counted instead.
    View(instrument_name='flower.task.runtime.seconds', aggregation=DropAggregation()),
)

_configured = False


def is_enabled() -> bool:
    return bool(os.environ.get('OTEL_EXPORTER_OTLP_ENDPOINT'))


def configure() -> bool:
    """Install the SDK providers and instrumentations in this process; returns False when no OTLP endpoint is set."""
    global _configured  # noqa: PLW0603
    # Loading settings first reads .env, which may hold the endpoint.
    environment = settings.ENVIRONMENT
    if _configured or not is_enabled():
        return _configured
    # The stable HTTP conventions label metrics with http.route, not the client-chosen Host header.
    os.environ.setdefault('OTEL_SEMCONV_STABILITY_OPT_IN', 'http')

    # One instance per process: each gunicorn worker and Celery child keeps its own cumulative counters.
    resource = Resource.create({'deployment.environment.name': environment, 'service.instance.id': uuid.uuid4().hex})

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(timeout=EXPORT_TIMEOUT_SECONDS)))
    trace.set_tracer_provider(tracer_provider)

    reader = PeriodicExportingMetricReader(OTLPMetricExporter(timeout=EXPORT_TIMEOUT_SECONDS))
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader], views=METRIC_VIEWS))

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter(timeout=EXPORT_TIMEOUT_SECONDS)))
    set_logger_provider(logger_provider)

    DjangoInstrumentor().instrument(excluded_urls=EXCLUDED_URLS, response_hook=_tag_correlation_id)
    PsycopgInstrumentor().instrument()
    RedisInstrumentor().instrument()
    CeleryInstrumentor().instrument()
    URLLibInstrumentor().instrument()
    _configured = True
    return True


def shutdown() -> None:
    """Flush buffered telemetry; Celery pool children exit through os._exit, which skips the SDK's atexit flush."""
    if not _configured:
        return
    trace.get_tracer_provider().shutdown()
    metrics.get_meter_provider().shutdown()
    get_logger_provider().shutdown()


def _tag_correlation_id(span, request, response) -> None:
    cid = response.get(settings.DJANGO_GUID['GUID_HEADER_NAME'])
    if cid and span.is_recording():
        span.set_attribute('cid', cid)
