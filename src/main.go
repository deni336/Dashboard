package main

import (
	clienthdlr "chat/pkg/clienthandler"
	"flag"
	"fmt"
)

/*
# TODO
- [] may need to re-structure active users
- [] Add file manager to setup storage and screen share support
- [] Write test for this code
- [] Add ability to save snapshot to screen share
- [X] Add gRPC for API for deni
*/

var (
	CHAT = flag.String("addr", "localhost:6969", "the address to connect to")
)

func main() {
	startChatServer()
}

func startChatServer() {
	err := clienthdlr.Run(CHAT)
	if err != nil {
		fmt.Println("failed setting up chat server")
	}
}
