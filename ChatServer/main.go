package main

import (
	"chat/internal/screenshare"
	"chat/internal/storage"
	"chat/pkg/clienthandler"
	"fmt"
)

/*
# TODO
- [] may need to re-structure active users
- [] Add file manager to setup storage and screen share support
- [] Write test for this code
- [] Add ability to save snapshot to screen share
- [] Add gRPC for API for deni


# ScreenShare API:
- [] List of all users


# File Upload API:
- [X] endpoint for uploading

*/

var (
	CHAT       = "localhost:6969"
	SCRNSHR    = "localhost:7070"
	FILEUPLOAD = "localhost:7777"
)

var atv_usrs = clienthandler.InitializeActiveUserList()

func main() {

	fmt.Println("Created active user list")

	startSupportingServers(atv_usrs)

	startChatServer(atv_usrs)
}

func startSupportingServers(au *clienthandler.ActiveUsers) {
	fmt.Println("Initializing screen share server...")
	go screenshare.InitScreenShareServer(SCRNSHR)

	fmt.Println("Initializing file upload server...")
	go storage.HostUploadServer(FILEUPLOAD)
}

func startChatServer(atv_usrs *clienthandler.ActiveUsers) {
	fmt.Println("Initializing chat server...")

	err := clienthandler.Run(CHAT)
	if err != nil {
		fmt.Println("failed setting up chat server")
	}
}
