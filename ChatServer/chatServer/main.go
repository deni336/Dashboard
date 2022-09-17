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
# Clienthandler:
- [] clienthandler main clean up.
- [X] active users hash table
- [X] user object
- [] Add some print statements for troubleshooting purposes
- [] Chat handler needs to get cleaned up
- [] Clean up Screenshare and Uploader
- [] Write test for this code
- [] Add ability to save snapshot to screen share
- [] need to add a check in storage server for working dir
*/
var (
	CHAT       = "192.168.45.10:6969"
	SCRNSHR    = "192.168.45.10:7070"
	FILEUPLOAD = "192.168.45.10:7777"
	//APIIP      = "192.168.45.10:1337"
)

func main() {
	atv_usrs := clienthandler.InitializeActiveUserList()
	fmt.Println("Created active user list")

	fmt.Println("Initializing screen share server...")
	go screenshare.InitScreenShareServer(SCRNSHR)

	fmt.Println("Initializing file upload server...")
	go storage.HostUploadServer(FILEUPLOAD)

	fmt.Println("Initializing chat server...")
	clientListener := clienthandler.ClientListener(CHAT)
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
		// need to send data out to deni
		//active_users <- atv_usrs.Serialize()
		go clienthandler.HandleConnection(user)
	}
}
