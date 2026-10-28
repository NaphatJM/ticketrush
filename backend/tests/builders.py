from accounts.models import User


def make_user(**overrides) -> User:
    fields = {'username': 'buyer', 'password': 'not-a-real-password'} | overrides
    password = fields.pop('password')
    return User.objects.create_user(password=password, **fields)
