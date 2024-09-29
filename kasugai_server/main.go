package main

import (
	"chat/internal/screenshare"
	"chat/pkg/server"
	"chat/pkg/stdlog"
	"fmt"
	"log"
	"os"
)

/*
# TODO
- [] Write test for this code
- [] fix screen sharing
- [] database
*/

func main() {
	chataddr := "localhost:8008" // Default address
	saddy := "localhost:7070"

	if len(os.Args) > 1 {
		chataddr = os.Args[1]
	} else {
		fmt.Println("No address provided, using default:", chataddr)
	}

	go screenshare.InitScreenShareServer(saddy)

	startChatServer(chataddr)
}

func startChatServer(address string) {
	logger, err := stdlog.NewLogger("server.log", stdlog.INFO, true)
	if err != nil {
		log.Fatalf("Failed to create logger: %v", err)
	}
	defer logger.Close()

	if err := server.StartServer(address, logger); err != nil {
		logger.Fatal(fmt.Sprintf("Server failed to start: %v", err))
	}
	fmt.Printf("Starting server on %s...\n", address)
}
