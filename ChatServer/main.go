package main

import (
	"chat/internal/screenshare"
	"chat/internal/storage"
	"chat/pkg/api"
	"chat/pkg/clienthandler"
	"chat/pkg/utils"
	"fmt"
	"log"
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
	APIIP      = "localhost:1337"
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

	fmt.Println("Initializing chat server API...")
	api.API(APIIP, au)
}

func startChatServer(atv_usrs *clienthandler.ActiveUsers) {
	fmt.Println("Initializing chat server...")

	srv, err := clienthandler.Run(CHAT)
	if err != nil {
		fmt.Println("failed setting up chat server")
	}

	for {
		conn, err := clientListener.Accept()
		if err != nil {
			log.Print(err)
			fmt.Println("Failed to start chat server")
			continue
		}

		user := &clienthandler.User{
			Name:        utils.ReadBuf(conn),
			Address:     conn.RemoteAddr().String(),
			Connection:  conn,
			IsConnected: true,
		}

		atv_usrs.Add(user.Name, user)
		fmt.Println("User created and added to active_user list")
		fmt.Println(atv_usrs.ListUsers())
		go clienthandler.HandleConnection(user)
	}
}

func ACTIVE_USRS() *clienthandler.ActiveUsers {
	return atv_usrs
}
