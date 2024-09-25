package main

import (
	"chat/internal/screenshare"
	"chat/pkg/server"
	"fmt"
	"os"
)

/*
# TODO
- [] Add file manager to setup storage and screen share support
- [] Write test for this code
- [] Add ability to save snapshot to screen share
- [] fix screen sharing
- [] add video streaming
- [] database
*/

func main() {
	chataddr := "localhost:6969" // Default address
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
	fmt.Printf("Starting server on %s...\n", address)
	server.StartServer(address)
}
