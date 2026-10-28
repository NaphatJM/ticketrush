"""Envelope codes. Clients switch on `status.code`, so changing a string here changes the API."""

CODE_SUCCESS = 'SUCCESS'
MESSAGE_SUCCESS = 'Success.'

CODE_BAD_REQUEST = 'BAD_REQUEST'
CODE_NOT_AUTHENTICATED = 'NOT_AUTHENTICATED'
CODE_FORBIDDEN = 'FORBIDDEN'
CODE_NOT_FOUND = 'NOT_FOUND'
CODE_INTERNAL_SERVER_ERROR = 'INTERNAL_SERVER_ERROR'

MESSAGE_BAD_REQUEST = 'Bad request.'
# Never reveal whether the account exists, the password was wrong, or the account is disabled.
MESSAGE_NOT_AUTHENTICATED = 'Authentication credentials were not provided or are invalid.'
MESSAGE_FORBIDDEN = 'Permission denied.'
MESSAGE_NOT_FOUND = 'Not found.'
MESSAGE_INTERNAL_SERVER_ERROR = 'Internal server error.'
