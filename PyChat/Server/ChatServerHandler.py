import grpc
import __future__

class ServerCreation():
    def __init__(self) -> None:
        self.serverInstance = grpc.server(futures, handlers=None, interceptors=None, options=None, maximum_concurrent_rpcs=None, compression=None, xds=False)

class CreateServerAuth():
    def __init__(self) -> None:
        serverAuthKey = grpc.ssl_server_credentials(private_key_certificate_chain_pairs=, root_certificates=None, require_client_auth=False)