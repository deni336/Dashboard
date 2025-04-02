# GlobalLogger Documentation

## Summary
The `GlobalLogger` class provides a method to create and configure a logger with a specified name. It sets up logging to both a file and the console, using configurations from a `ConfigHandler` instance. The log files are stored in a user-specific directory and are named based on the current date.

___
## Example Usage
```python
logger = GlobalLogger.get_logger("my_logger")
logger.info("This is an info message.")
```
This will create a logger named "my_logger" that logs messages to both a file and the console. The log file will be stored in a directory specified in the configuration and will be named with the current date.

___
## Code Analysis
### Main functionalities
The main functionality of the `GlobalLogger` class is to provide a centralized way to create and configure loggers with file and console handlers, using configurations for log directory and log level.
### Methods
- `get_logger(cls, name)`: Class method that returns a logger configured with file and console handlers. It sets the log level and ensures the log directory exists.
### Fields
- `config`: An instance of `ConfigHandler` used to retrieve logging configurations such as log path and log level.

