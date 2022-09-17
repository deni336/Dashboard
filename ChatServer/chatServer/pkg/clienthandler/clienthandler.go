package clienthandler

import (
	"bufio"
	"fmt"
	"log"
	"net"
)

type client chan<- string // an outgoing message channel

var (
	entering = make(chan client)
	leaving  = make(chan client)
	messages = make(chan string) // all incoming client messages
)

func ClientListener(addr string) net.Listener {
	chatConn, err := net.Listen("tcp", addr)
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println("[success!] chat server online and listening on", addr)
	go broadcast()
	return chatConn
}

func HandleConnection(u *User) {
	ch := make(chan string) // outgoing client message

	fmt.Fprintln(u.Connection, "Connection made successfully")

	defer u.Connection.Close()

	go u.ClientWriter(ch)

	handleInput(u, ch)

	leaving <- ch
	messages <- u.Name + " has left"

	u.IsConnected = false
}

func broadcast() {
	clients := make(map[client]bool) // all connected clients

	for {
		select {
		case msg := <-messages:
			// Broadcast the message to all connected clients
			// clients outgoin message channel
			for cli := range clients {
				cli <- msg
				fmt.Println("message broadcasted => ", msg)
			}
		case cli := <-entering:
			clients[cli] = true
		case cli := <-leaving:
			delete(clients, cli)
			close(cli)
		}
	}
}

func handleInput(u *User, ch chan string) {
	ch <- "You are " + u.Name
	messages <- "Welcome " + u.Name
	entering <- ch
	input := bufio.NewScanner(u.Connection)
	for input.Scan() {
		messages <- u.Name + ": " + input.Text()
	}
	// Need to handle errors from input.Err()
}
