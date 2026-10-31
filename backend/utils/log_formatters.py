import json
import logging
from datetime import UTC
from datetime import datetime

from opentelemetry import trace


_RESERVED = frozenset(logging.LogRecord(name='', level=0, pathname='', lineno=0, msg='', args=(), exc_info=None).__dict__) | {
    'message',
    'asctime',
    'taskName',
    'correlation_id',
    'celery_parent_id',
    'celery_current_id',
}


class JsonFormatter(logging.Formatter):
    """One JSON object per line; `extra=` fields are added at the top level."""

    def __init__(self, service: str = '', environment: str = ''):
        super().__init__()
        self.service = service
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            'ts': datetime.fromtimestamp(record.created, UTC).isoformat(timespec='milliseconds'),
            'level': record.levelname,
            'service': self.service,
            'env': self.environment,
            'cid': getattr(record, 'correlation_id', '') or '',
            'logger': record.name,
            'module': record.module,
            'func': record.funcName,
            'line': record.lineno,
            'msg': record.getMessage(),
        }
        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            payload['trace_id'] = trace.format_trace_id(span_context.trace_id)
            payload['span_id'] = trace.format_span_id(span_context.span_id)
        celery_current = getattr(record, 'celery_current_id', None)
        if celery_current:
            payload['celery_current_id'] = celery_current
            payload['celery_parent_id'] = getattr(record, 'celery_parent_id', None)
        for key, value in record.__dict__.items():
            if key not in _RESERVED and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload['exc'] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)
