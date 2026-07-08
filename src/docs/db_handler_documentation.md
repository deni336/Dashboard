# ChatHistory Documentation

## Summary
The `ChatHistory` class manages chat messages stored in a SQLite database at `~/Kasugai/<Database.dbpath>`. Message content is encrypted at rest with `cryptography.fernet.Fernet`, using a key stored in config (generated on first run if absent). It provides methods to add, view, and erase messages, while logging operations and errors using a global logger.

___
## Example Usage
```python
chat_history = ChatHistory()
chat_history.add_message('Alice', 'Hello, World!', '2023-10-01T10:00:00')
messages = chat_history.view_messages()
chat_history.erase_history()
```

___
## Code Analysis
### Main functionalities
The class handles the storage and retrieval of encrypted chat messages in a SQLite database, and logs actions and errors.
### Methods
- `__init__`: Loads or generates the Fernet encryption key, resolves the SQLite database path from config, and creates the `chat_history` table if it doesn't exist.
- `add_message`: Encrypts and inserts a new message row, and logs the action.
- `view_messages`: Retrieves all rows, decrypts their message content, and returns them ordered by timestamp.
- `erase_history`: Deletes all rows from the `chat_history` table and logs the action.
### Fields
- `db_path`: Stores the resolved path to the SQLite database file.
- `fernet`: The `Fernet` instance used to encrypt/decrypt message content.
- `logger`: An instance of a logger for logging operations and errors.

