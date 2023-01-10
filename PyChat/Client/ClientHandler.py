import grpc
import grpc_tools


class client():
    def __init__(self) -> None:
        AuthKey = CreateAuth.createKey()
        grpc.secure_channel("localhost", options=None, compression=None)
        AuthKey = CreateAuth.createKey()

    def getFeature(self, request, context):
        feature = get_feature(self.db, request)
        if feature is None:
            return route_guide_pb2.Feature(name="", location=request)
        else:
            return feature

class CreateAuth():
    def createKey():
        AuthKey = grpc.ssl_channel_credentials(root_certificates=None, private_key=None, certificate_chain=None)
        return AuthKey