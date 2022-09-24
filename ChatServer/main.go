package main

import (
	"chat/internal/screenshare"
	"chat/internal/storage"
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
*/

var (
	CHAT       = "localhost:6969"
	SCRNSHR    = "localhost:7070"
	FILEUPLOAD = "localhost:7777"
	//APIIP      = "192.168.45.10:1337"
)

func main() {
	atv_usrs := clienthandler.InitializeActiveUserList()
	fmt.Println("Created active user list")

	startSupportingServers()

	startChatServer(atv_usrs)
}

func startSupportingServers() {
	fmt.Println("Initializing screen share server...")
	go screenshare.InitScreenShareServer(SCRNSHR)

	fmt.Println("Initializing file upload server...")
	go storage.HostUploadServer(FILEUPLOAD)
}

func startChatServer(atv_usrs *clienthandler.ActiveUsers) {
	fmt.Println("Initializing chat server...")

	clientListener, err := clienthandler.ClientListener(CHAT)
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

		atv_usrs.Add(user.Name)
		fmt.Println("User created and added to active_user list")

		go clienthandler.HandleConnection(user)
	}
}
