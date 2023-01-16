
import grpc
import kasugaipy_pb2
import kasugaipy_pb2_grpc

def make_message(message):
    return kasugaipy_pb2.MessageResponse(
        message=message
    )

def generate_messages():
    messages = [
        make_message("First message"),
        make_message("Second message"),
        make_message("Third message"),
        make_message("Fourth message"),
        make_message("Fifth message"),
    ]
    for msg in messages:
        print("Hello Server Sending you the %s" % msg.message)
        yield msg


def send_message(stub):
    responses = stub.ChatService(generate_messages())
    for response in responses:
        print("Hello from the server received your %s" % response.message)


def run():
    with grpc.insecure_channel('localhost:6969') as channel:
        stub = kasugaipy_pb2_grpc.BroadcastStub(channel)
        send_message(stub)

if __name__ == '__main__':
    run()