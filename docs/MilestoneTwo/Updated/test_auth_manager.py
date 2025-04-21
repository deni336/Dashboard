import unittest
from auth_manager import AuthManager

class TestAuthManager(unittest.TestCase):
    def setUp(self):
        self.auth = AuthManager()

    def test_is_authenticated(self):
        self.assertTrue(self.auth.is_authenticated())

    def test_login_logout(self):
        self.assertTrue(self.auth.login({'username': 'test'}))
        self.assertTrue(self.auth.logout('user_id'))

if __name__ == '__main__':
    unittest.main()
