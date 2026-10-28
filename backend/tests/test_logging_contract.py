import json
import logging
import sys

from django.conf import settings

from utils.log_formatters import JsonFormatter


def test_root_logger_is_configured():
    assert settings.LOGGING['root']['handlers']


def test_every_handler_adds_the_correlation_id():
    for name, handler in settings.LOGGING['handlers'].items():
        assert 'correlation_id' in handler.get('filters', []), f'handler {name!r} drops the cid'


def test_every_local_app_has_a_logger():
    for app in settings.LOCAL_APPS:
        assert app in settings.LOGGING['loggers'], f'app {app!r} logs would fall through to root'


def test_json_lines_carry_the_required_fields():
    record = logging.LogRecord('ticketrush.test', logging.INFO, __file__, 10, 'hold %s', ('created',), None)
    record.correlation_id = 'abc123'
    record.event_id = 'evt-1'

    line = json.loads(JsonFormatter(service='ticketrush-api', environment='test').format(record))

    assert line['cid'] == 'abc123'
    assert line['msg'] == 'hold created'
    assert line['service'] == 'ticketrush-api'
    assert line['event_id'] == 'evt-1'
    assert {'ts', 'level', 'env', 'logger', 'module', 'func', 'line'} <= line.keys()


def test_exceptions_are_kept_in_one_line():
    try:
        raise ValueError('boom')
    except ValueError:
        record = logging.LogRecord('ticketrush.test', logging.ERROR, __file__, 10, 'failed', (), exc_info=True)
        record.exc_info = sys.exc_info()

    output = JsonFormatter().format(record)

    assert '\n' not in output
    assert 'ValueError: boom' in json.loads(output)['exc']
