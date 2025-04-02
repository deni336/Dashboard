# ServerStorage Documentation

## Summary
The `ServerStorage` class manages a SQLite database for storing user, room, and message data. It initializes the database, provides methods to add, update, retrieve, and list users and rooms, and handles message storage and retrieval. It uses a logger for logging operations and errors.

___
## Example Usage
```python
storage = ServerStorage()
storage.add_user("user123", "Alice", "online")
user = storage.get_user("user123")
print(user)  # Output: ('user123', 'Alice', 'online')

storage.add_room("room456", "General", ["user123"], "public", "user123", "password")
room = storage.get_room("room456")
print(room)  # Output: {'room_id': 'room456', 'name': 'General', 'participant_ids': ['user123'], 'type': 'public', 'creator_id': 'user123', 'password': 'password'}

storage.add_message("msg789", "room456", "user123", "Hello, world!")
messages = storage.get_messages_for_room("room456")
print(messages)  # Output: [('msg789', 'room456', 'user123', 'Hello, world!', '2023-10-10T12:00:00')]
```

___
## Code Analysis
### Main functionalities
- Initializes and manages a SQLite database for users, rooms, and messages.
- Provides thread-safe methods to add, update, retrieve, and list users and rooms.
- Handles message storage, retrieval, and deletion.
### Methods
- `__init__`: Initializes the database and logger.
- `get_connection`: Returns a new SQLite connection.
- `init_db`: Creates necessary tables if they don't exist.
- `add_user`, `update_user_status`, `get_user`, `list_users`: Manage user records.
- `add_room`, `get_room`, `list_rooms`: Manage room records.
- `add_message`, `get_messages_for_room`, `delete_messages_for_room`: Manage message records.
### Fields
- `logger`: Logger instance for logging operations.
- `db_file`: Path to the SQLite database file.
- `_db_lock`: Thread lock for database operations.

