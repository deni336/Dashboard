# DatabaseCreation Documentation

## Summary
The `DatabaseCreation` class is responsible for creating a database table named `HIST` if it doesn't already exist. It uses SQLite for database operations and logs the process using a global logger.

___
## Example Usage
```python
db_creator = DatabaseCreation('path/to/database.db')
db_creator.create_table()
```
This will create a `HIST` table in the specified database file and log the creation process.

___
## Code Analysis
### Main functionalities
The main functionality of the `DatabaseCreation` class is to ensure the existence of the `HIST` table in a specified SQLite database and log the operations performed.
### Methods
- `__init__(self, db_path)`: Initializes the class with a database path and sets up a logger.
- `create_table(self)`: Creates the `HIST` table if it doesn't exist and logs the success or any errors encountered.
### Fields
- `db_path`: Stores the path to the SQLite database file.
- `logger`: An instance of a logger obtained from `GlobalLogger` to log information and errors.

# ChatHistory Documentation

## Summary
The `ChatHistory` class manages chat messages stored in a SQLite database. It provides methods to add, view, and erase messages, while logging operations and errors using a global logger.

___
## Example Usage
```python
chat_history = ChatHistory('path/to/database.db')
chat_history.add_message('Alice', 'Hello, World!', '2023-10-01 10:00:00')
messages = chat_history.view_messages()
chat_history.erase_history()
```

___
## Code Analysis
### Main functionalities
The class handles the storage and retrieval of chat messages in a database, and logs actions and errors.
### Methods
- `__init__`: Initializes the class with a database path and sets up a logger.
- `add_message`: Inserts a new message into the database and logs the action.
- `view_messages`: Retrieves all messages from the database and logs the number of messages fetched.
- `erase_history`: Deletes all messages from the database and logs the action.
### Fields
- `db_path`: Stores the path to the SQLite database.
- `logger`: An instance of a logger for logging operations and errors.

