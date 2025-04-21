from webserver import WebServer

class ServerFactory:
    @staticmethod
    def create_server(server_type):
        if server_type == "WebServer":
            return WebServer()
        # Placeholder for future server types
        raise ValueError(f"Unknown server type: {server_type}")
