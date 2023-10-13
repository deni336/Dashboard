import grpc
import kasugai_pb2
import kasugai_pb2_grpc
import time

ADDRESS = "localhost:6969"
CLIENT_ID = "python-client"
CLIENT_NAME = "PythonClient"

def register_client(stub):
    response = stub.RegisterClient(
        kasugai_pb2.ClientInfo(clientId=CLIENT_ID, clientName=CLIENT_NAME)
    )
    print(f"Registration Response: {response.message}")

def send_heartbeat(stub):
    response = stub.SendHeartbeat(
        kasugai_pb2.Heartbeat(clientId=CLIENT_ID, timestamp=int(time.time()))
    )
    print(f"Heartbeat Response: {response.message}")

def list_registered_clients(stub):
    response = stub.ListRegisteredClients(
        kasugai_pb2.ListClientsRequest(limit=10, offset=0)
    )
    for client in response.clients:
        print(f"Client: {client.clientId} - {client.clientName}")

def send_message(stub):
    response = stub.SendMessage(
        kasugai_pb2.Message(
            senderId=CLIENT_ID,
            recipientId="recipient-id",  # Replace with an actual recipient ID
            content="Hello from Python!",
            timestamp=int(time.time())
        )
    )
    print(f"Message Send Response: {response.message}")

def main():
    # Set up a connection to the server
    with grpc.insecure_channel(ADDRESS) as channel:
        stub = kasugai_pb2_grpc.ChatServiceStub(channel)
        
        register_client(stub)
        send_heartbeat(stub)
        list_registered_clients(stub)
        send_message(stub)
        
        # You can add more RPC calls as necessary

if __name__ == "__main__":
    main()
