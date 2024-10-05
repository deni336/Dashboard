package main

import (
	"chat/pkg/datastore"
	"chat/pkg/server"
	"chat/pkg/stdlog"
	"encoding/json"
	"fmt"
	"os"
	"os/signal"
	"sync"
	"syscall"
)

// Config struct to hold the chat server address, logging details, and other settings
type Config struct {
	ChatAddress         string    `json:"chat_address"`
	FileTransferAddress string    `json:"file_transfer_address"`
	MediaAddress        string    `json:"media_address"`
	LogFile             string    `json:"log_file"`
	LogLevel            string    `json:"log_level"`
	MaxClients          int       `json:"max_clients"`
	TLSConfig           TLSConfig `json:"tls_config"`
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
			ChatAddress:         "localhost:8008",
			FileTransferAddress: "localhost:50051",
			MediaAddress:        "localhost:50052",
			LogFile:             "server.log",
			LogLevel:            "info",
			MaxClients:          100,
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
		fmt.Println("No address override provided, attempting to read from config:", config.ChatAddress)
	}

	// Set up logging based on config.
	logger, err := setupLogging(config)
	if err != nil {
		fmt.Println("Error setting up logging:", err)
	}
	defer logger.Close()

	// Initialize the shared data store
	ds := datastore.GetInstance()
	logger.Info("Shared datastore initialized")

	// Create a channel to signal server shutdown
	shutdown := make(chan struct{})

	// Start all servers concurrently
	var wg sync.WaitGroup
	wg.Add(3)

	var chatServer *server.Server
	var fileTransferServer *server.FileTransferServer
	var mediaServer *server.MediaServer

	startServer := func(name string, serverStart func() error) {
		defer wg.Done()
		go func() {
			if err := serverStart(); err != nil {
				logger.Error(fmt.Sprintf("%s server failed: %v", name, err))
				close(shutdown)
			}
		}()
	}

	startServer("Chat", func() error {
		chatServer = server.NewServer(logger, ds)
		return chatServer.Start(config.ChatAddress)
	})

	startServer("File Transfer", func() error {
		fileTransferServer = server.NewFileTransferServer(logger, ds)
		return fileTransferServer.Start(config.FileTransferAddress)
	})

	startServer("Media", func() error {
		mediaServer = server.NewMediaServer(logger, ds)
		return mediaServer.Start(config.MediaAddress)
	})

	logger.Info("All servers started successfully")

	// Set up signal catching
	signals := make(chan os.Signal, 1)
	signal.Notify(signals, syscall.SIGINT, syscall.SIGTERM)

	// Wait for shutdown signal
	select {
	case <-signals:
		logger.Info("Shutdown signal received")
	case <-shutdown:
		logger.Info("Shutting down due to server failure")
	}

	// Graceful shutdown
	if chatServer != nil {
		chatServer.Stop()
	}
	if fileTransferServer != nil {
		fileTransferServer.Stop()
	}
	if mediaServer != nil {
		mediaServer.Stop()
	}

	// Wait for all servers to finish
	wg.Wait()
	logger.Info("All servers shut down successfully")
}
