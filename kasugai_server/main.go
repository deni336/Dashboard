package main

import (
	"chat/pkg/server"
	"fmt"
	"os"
)

/*
# TODO
- [] Add file manager to setup storage and screen share support
- [] Write test for this code
- [] Add ability to save snapshot to screen share
*/

func main() {
	chataddr := "localhost:6969" // Default address

	if len(os.Args) > 1 {
		chataddr = os.Args[1]
	} else {
		fmt.Println("No address provided, using default:", chataddr)
	}

	startChatServer(chataddr)
}

func startChatServer(address string) {
	fmt.Printf("Starting server on %s...\n", address)
	server.StartServer(address)
}
