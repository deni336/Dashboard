import grpc
import kasugai_pb2
import kasugai_pb2_grpc
import time
import threading

ADDRESS = "localhost:8008"
CLIENT_ID = "python-client"
CLIENT_NAME = "PythonClient"
RECIPIENT_ID = "recipient-client"  # Replace with an actual recipient ID

def register_client(stub):
    response = stub.RegisterClient(
        kasugai_pb2.User(
            uuid=kasugai_pb2.Id(uuid=CLIENT_ID),  # User now uses `Id` for uuid
            name=CLIENT_NAME
        )
    )
    print(f"Registration Response: {response.message}")

def list_registered_clients(stub):
    response = stub.ActiveUsers(kasugai_pb2.ActiveUsersRequest())
    for client in response.users:
        print(f"Client: {client.uuid.uuid} - {client.name}")

def send_message(stub, recipient_id, content):
    response = stub.SendMessage(
        kasugai_pb2.Message(
            senderId=CLIENT_ID,
            recipientId=recipient_id,  # The recipient of the message
            content=content,  # Message content from user input
            timestamp=int(time.time())
        )
    )
    print(f"Message Send Response: {response.message}")

def receive_messages(stub):
    # Start receiving messages
    try:
        response_stream = stub.ReceiveMessages(kasugai_pb2.Id(uuid=CLIENT_ID))

        # Continuously listen for new messages
        for message in response_stream:
            print(f"Received Message from {message.senderId}: {message.content}")
    
    except grpc.RpcError as e:
        print(f"Error receiving messages: {e}")

def chat_interface(stub):
    # This function will allow the user to send multiple messages in a loop
    print("You can start chatting. Type 'exit' to quit.")
    while True:
        content = input("Enter your message: ")
        if content.lower() == 'exit':
            break
        send_message(stub, RECIPIENT_ID, content)

def main():
    # Set up a connection to the server
    with grpc.insecure_channel(ADDRESS) as channel:
        stub = kasugai_pb2_grpc.ChatServiceStub(channel)
        
        # Register the client
        register_client(stub)

        # Start a separate thread to receive messages in the background
        receive_thread = threading.Thread(target=receive_messages, args=(stub,), daemon=True)
        receive_thread.start()

        # Start the chat interface to send messages
        chat_interface(stub)

        # Wait for the receive thread to finish before exiting
        receive_thread.join()

if __name__ == "__main__":
    main()
