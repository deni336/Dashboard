import grpc
import kasugai_pb2
import kasugai_pb2_grpc
import time
import cv2  # Assuming you will use OpenCV for screen capture
import numpy as np

ADDRESS = "localhost:6969"
CLIENT_ID = "python-client"
CLIENT_NAME = "PythonClient"

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

def start_screen_share(stub):
    # Capture the screen using OpenCV (you can use another tool if preferred)
    cap = cv2.VideoCapture(0)  # This would capture webcam; replace it with screen capture logic
    
    # Send screen data in a stream
    def screen_share_stream():
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            # Encode the frame as bytes and send it via gRPC
            _, buffer = cv2.imencode('.jpg', frame)
            frame_bytes = buffer.tobytes()

            yield kasugai_pb2.ScreenShare(
                streamId=kasugai_pb2.Id(uuid=CLIENT_ID),  # Set the stream ID
                data=frame_bytes
            )
    
    # Start streaming screen frames
    response = stub.StartScreenShare(screen_share_stream())
    print(f"Screen Share Ended: {response.message}")

def watch_screen_share(stub):
    # Watching a screen share stream
    response_stream = stub.WatchScreenShare(kasugai_pb2.Id(uuid=CLIENT_ID))
    
    for screen_frame in response_stream:
        # Process the incoming frames (in your case, you would send this to the frontend)
        print(f"Received frame of size: {len(screen_frame.data)} bytes")

def main():
    # Set up a connection to the server
    with grpc.insecure_channel(ADDRESS) as channel:
        stub = kasugai_pb2_grpc.ChatServiceStub(channel)
        
        register_client(stub)
        #list_registered_clients(stub)
        send_message(stub)
        
        # Start screen share
        start_screen_share(stub)
        watch_screen_share(stub)

if __name__ == "__main__":
    main()
