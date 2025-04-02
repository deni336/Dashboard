# ChatManager Documentation

## Summary
The `ChatManager` class manages chat functionalities, including user registration, room creation, joining rooms, sending messages, and listening for incoming messages. It integrates with a gRPC client (`KasugaiClient`) and uses Flask-SocketIO for real-time communication.

___
## Example Usage
```python
from flask import Flask
from src.chat_manager import ChatManager

app = Flask(__name__)
chat_manager = ChatManager(app, "JohnDoe")

# Register a user
user = chat_manager.register_user("JohnDoe")

# Create a chat room
room_info = chat_manager.create_room("General", "password123")

# Join an existing room
chat_manager.join_room("General", "password123")

# Send a message
chat_manager.send_message("Hello, World!")
```

___
## Code Analysis
### Main functionalities
The main functionalities of the `ChatManager` class include user registration, room creation and joining, sending messages, and listening for incoming messages. It also handles logging and error management.
### Methods
- `__init__`: Initializes the `ChatManager` with configurations, logging, and sets up the gRPC client and SocketIO.
- `register_user`: Registers a new user with the chat service.
- `create_room`: Creates a new chat room and joins it.
- `join_room`: Joins an existing chat room.
- `send_message`: Sends a text message to the current room.
- `start_listening`: Starts a thread to listen for incoming messages.
- `listen_for_messages`: Continuously listens for incoming messages and emits them via SocketIO.
### Fields
- `logger`: Logger for logging messages and errors.
- `config`: Configuration handler for retrieving settings.
- `chat_history`: Manages chat history storage.
- `socketio`: SocketIO instance for real-time communication.
- `client`: Instance of `KasugaiClient` for gRPC communication.
- `user`: The current registered user.
- `current_room`: The current room the user is in.

