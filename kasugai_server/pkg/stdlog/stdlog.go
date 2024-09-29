package stdlog

import (
	"bufio"
	"fmt"
	"os"
	"sync"
	"time"
)

// LogLevel represents the severity of a log message
type LogLevel int

const (
	DEBUG LogLevel = iota
	INFO
	WARNING
	ERROR
	FATAL
)

// String returns the string representation of a LogLevel
func (l LogLevel) String() string {
	return [...]string{"DEBUG", "INFO", "WARNING", "ERROR", "FATAL"}[l]
}

// Logger is a custom logger that writes to both file and console
type Logger struct {
	file       *os.File
	writer     *bufio.Writer
	ch         chan logMessage
	level      LogLevel
	mu         sync.Mutex
	consoleLog bool
}

type logMessage struct {
	level   LogLevel
	message string
}

// NewLogger creates a new Logger instance
func NewLogger(filename string, level LogLevel, consoleLog bool) (*Logger, error) {
	file, err := os.OpenFile(filename, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		return nil, err
	}

	logger := &Logger{
		file:       file,
		writer:     bufio.NewWriter(file),
		ch:         make(chan logMessage, 1000), // Buffer for 1000 log messages
		level:      level,
		consoleLog: consoleLog,
	}

	go logger.writeLoop()

	return logger, nil
}

// writeLoop continuously writes log messages from the channel to the file
func (l *Logger) writeLoop() {
	for msg := range l.ch {
		logLine := l.formatLogMessage(msg.level, msg.message)
		_, err := l.writer.WriteString(logLine + "\n")
		if err != nil {
			fmt.Println("Error writing to log file:", err)
		}
		l.writer.Flush()
	}
}

// formatLogMessage creates a formatted log message with timestamp and log level
func (l *Logger) formatLogMessage(level LogLevel, message string) string {
	timestamp := time.Now().Format("2006-01-02 15:04:05")
	return fmt.Sprintf("[%s] [%s] %s", timestamp, level.String(), message)
}

// log logs a message at the specified level
func (l *Logger) log(level LogLevel, message string) {
	if level >= l.level {
		logMsg := logMessage{level: level, message: message}

		// Non-blocking write to channel for file logging
		select {
		case l.ch <- logMsg:
		default:
			fmt.Println("Warning: Log buffer full, message dropped")
		}

		// Console logging if enabled
		if l.consoleLog {
			fmt.Println(l.formatLogMessage(level, message))
		}
	}
}

// Debug logs a debug message
func (l *Logger) Debug(message string) {
	l.log(DEBUG, message)
}

// Info logs an info message
func (l *Logger) Info(message string) {
	l.log(INFO, message)
}

// Warning logs a warning message
func (l *Logger) Warning(message string) {
	l.log(WARNING, message)
}

// Error logs an error message
func (l *Logger) Error(message string) {
	l.log(ERROR, message)
}

// Fatal logs a fatal message and exits the program
func (l *Logger) Fatal(message string) {
	l.log(FATAL, message)
	os.Exit(1)
}

// SetLevel sets the minimum log level
func (l *Logger) SetLevel(level LogLevel) {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.level = level
}

// Close closes the logger
func (l *Logger) Close() {
	close(l.ch)
	l.file.Close()
}
