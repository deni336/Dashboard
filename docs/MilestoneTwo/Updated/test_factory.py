import unittest
from factory import ServerFactory
from webserver import WebServer

class TestFactory(unittest.TestCase):
    def test_create_webserver(self):
        server = ServerFactory.create_server("WebServer")
        self.assertIsInstance(server, WebServer)

    def test_invalid_type(self):
        with self.assertRaises(ValueError):
            ServerFactory.create_server("InvalidType")

if __name__ == '__main__':
    unittest.main()
