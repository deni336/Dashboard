# KasugaiClient Documentation

## Summary
The `KasugaiClient` class is a client implementation for interacting with various gRPC services related to user management, room management, chat, media streaming, and file transfer. It initializes stubs for each service and provides methods to register users, create and join rooms, send and receive messages, and manage media streams.

___
## Example Usage
```python
client = KasugaiClient(host='localhost', port=8008)
user = client.register_user('Alice')
room_id = client.create_room('General', '', 'public', user.id.uuid)
client.join_room(room_id)
client.send_text_message('Hello, World!')
messages = client.receive_text_messages()
client.start_screen_share()
client.end_screen_share()
client.close()
```

___
## Code Analysis
### Main functionalities
- Initialize gRPC channel and service stubs.
- Register and manage user status.
- Create, join, and manage rooms.
- Send and receive chat messages.
- Start and end media streams.
### Methods
- `__init__`: Initializes the client with gRPC channel and service stubs.
- `register_user`: Registers a new user and updates their status.
- `create_room`: Creates a new room with specified parameters.
- `join_room`: Joins an existing room using room ID and password.
- `send_text_message`: Sends a text message to the current room.
- `receive_text_messages`: Receives text messages from the current room.
- `start_screen_share`: Starts a screen sharing media stream.
- `end_screen_share`: Ends the current screen sharing media stream.
- `close`: Closes the gRPC channel.
### Fields
- `logger`: Logger instance for logging client activities.
- `channel`: gRPC channel for communication with services.
- `user_stub`: Stub for user-related gRPC services.
- `room_stub`: Stub for room-related gRPC services.
- `chat_stub`: Stub for chat-related gRPC services.
- `media_stub`: Stub for media-related gRPC services.
- `file_stub`: Stub for file transfer-related gRPC services.
- `current_user`: Stores the current user object.
- `current_room_id`: Stores the ID of the current room.

