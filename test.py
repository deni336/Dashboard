import grpc
import kasugaipy_pb2_grpc 
import protos.clean_way.kasugaipy_pb2 as kasugaipy_pb2


class Client(object):
    """
    Client for gRPC functionality
    """

    def __init__(self):
        self.host = 'localhost'
        self.server_port = 6969

        # instantiate a channel
        self.channel = grpc.insecure_channel(
            '{}:{}'.format(self.host, self.server_port))

        # bind the client and the server
        self.stub = protos.kasugaipy_pb2_grpc.ChatService(self.channel)

    def get_url(self, message):
        """
        Client function to call the rpc for GetServerResponse
        """
        message = protos.kasugaipy_pb2.MessageResponse(message=message)
        print(f'{message}')
        return self.stub.GetServerResponse(message)


if __name__ == '__main__':
    client = Client()
    result = client.get_url(message="Hello Server you there?")
    print(f'{result}')