# ServerLogger Documentation

## Summary
The `ServerLogger` class provides a method to create and configure a logger for server applications. It sets up a logger with a file handler and a console handler, ensuring logs are stored in a specified directory and format.

___
## Example Usage
```python
logger = ServerLogger.get_logger("my_logger")
logger.info("This is an info message.")
```
This will create a logger named "my_logger" that logs messages to a file and the console. The log file is stored in a directory specified in the configuration, with the current date as the filename.

___
## Code Analysis
### Main functionalities
The main functionality of the `ServerLogger` class is to provide a logger configured with both file and console handlers, using settings from a configuration file.
### Methods
- `get_logger(cls, name)`: Configures and returns a logger with the specified name, setting up file and console handlers based on configuration settings.
### Fields
- `config`: An instance of `ServerConfig` used to retrieve logging configuration settings such as log directory and log level.

