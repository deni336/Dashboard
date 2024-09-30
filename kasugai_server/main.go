package main

import (
	"chat/internal/screenshare"
	"chat/pkg/server"
	"chat/pkg/stdlog"
	"encoding/json"
	"fmt"
	"os"
)

// Config struct to hold the chat server address, logging details, and other settings
type Config struct {
	ChatAddress        string    `json:"chat_address"`
	LogFile            string    `json:"log_file"`
	LogLevel           string    `json:"log_level"`
	ScreenShareAddress string    `json:"screen_share_address"`
	MaxClients         int       `json:"max_clients"`
	TLSConfig          TLSConfig `json:"tls_config"`
}

// TLSConfig struct to handle TLS (SSL) settings
type TLSConfig struct {
	Enabled  bool   `json:"enabled"`
	CertFile string `json:"cert_file"`
	KeyFile  string `json:"key_file"`
}

// loadConfig reads and parses the config file
func loadConfig(filePath string) (*Config, error) {
	file, err := os.ReadFile(filePath)
	if err != nil {
		return nil, err
	}

	var config Config
	err = json.Unmarshal(file, &config)
	if err != nil {
		return nil, err
	}

	return &config, nil
}

// setupLogging configures the log output and level based on the config.
func setupLogging(config *Config) (*stdlog.Logger, error) {
	logger, err := stdlog.NewLogger(config.LogFile, getLogLevel(config.LogLevel), true)
	if err != nil {
		return nil, fmt.Errorf("failed to create logger: %v", err)
	}

	return logger, nil
}

// getLogLevel maps log level strings to stdlog.LogLevel.
func getLogLevel(level string) stdlog.LogLevel {
	switch level {
	case "debug":
		return stdlog.DEBUG
	case "info":
		return stdlog.INFO
	case "warning":
		return stdlog.WARNING
	case "error":
		return stdlog.ERROR
	case "fatal":
		return stdlog.FATAL
	default:
		return stdlog.INFO
	}
}

func main() {
	// Load config file (config.json).
	config, err := loadConfig("config.json")
	if err != nil {
		fmt.Println("Error loading config file, using defaults:", err)
		config = &Config{
			ChatAddress:        "localhost:8008",
			LogFile:            "server.log",
			LogLevel:           "info",
			ScreenShareAddress: "0.0.0.0:6969",
			MaxClients:         100,
			TLSConfig: TLSConfig{
				Enabled:  false,
				CertFile: "",
				KeyFile:  "",
			},
		}
	}

	// Override with command line argument if provided.
	if len(os.Args) > 1 {
		config.ChatAddress = os.Args[1]
	} else {
		fmt.Println("No address override provided, using default or config:", config.ChatAddress)
	}

	// Set up logging based on config.
	logger, err := setupLogging(config)
	if err != nil {
		fmt.Println("Error setting up logging:", err)
	}
	defer logger.Close()

	go screenshare.InitScreenShareServer(config.ScreenShareAddress)

	// Start the chat server.
	if err := server.StartServer(config.ChatAddress, logger); err != nil {
		logger.Fatal(fmt.Sprintf("Server failed to start: %v", err))
	}
}
