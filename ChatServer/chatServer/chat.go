package main

import (
	"bufio"
	"bytes"
	storage "chat/FileStorage"
	shr "chat/ScreenShare"
	"fmt"
	"io"
	"log"
	"net"
	"os"
	"strings"
)

type client chan<- string // an outgoing message channel

type User struct {
	Msg         *client
	Name        string
	Address     string
	Connection  *net.Conn
	isConnected bool
}

var (
	entering = make(chan client)
	leaving  = make(chan client)
	messages = make(chan string) // all incoming client messages
)

func broadcast() {
	clients := make(map[client]bool) // all connected clients

	for {
		select {
		case msg := <-messages:
			// Broadcast the message to all connected clients
			// clients outgoin message channel
			for cli := range clients {
				cli <- msg
			}
		case cli := <-entering:
			clients[cli] = true
		case cli := <-leaving:
			delete(clients, cli)
			close(cli)
		}
	}
}

func clientWriter(conn net.Conn, ch <-chan string) {
	fmt.Fprintln(conn, "Connection made successfully")

	for msg := range ch {
		fmt.Fprintln(conn, msg)
		if msg[len(msg)-9:] == "/download" {
			a := msg[:len(msg)-9]
			rtn := strings.Split(a, ": ")
			fmt.Println("Transfering files...", strings.TrimSpace(rtn[1]))
			Copy(msg[:len(msg)-9], "./")
		}
	}
	fmt.Fprintln(conn, "Message sent to user")
}

func handleConnection(conn net.Conn, user User) {
	ch := make(chan string) // outgoing client message
	storage.HostUploader("192.168.45.69:8080")

	go clientWriter(conn, ch)
	user.isConnected = true
	who := user.Name
	ch <- "You are " + who
	messages <- "Welcome " + who
	entering <- ch

	input := bufio.NewScanner(conn)
	for input.Scan() {
		messages <- who + ": " + input.Text()
	}
	// Need to handle errors from input.Err()

	leaving <- ch
	messages <- who + " has left"
	conn.Close()
}

func Copy(srcFile, dstFile string) error {
	out, err := os.Create(dstFile)
	if err != nil {
		return err
	}
	defer out.Close()

	in, err := os.Open(srcFile)
	if err != nil {
		return err
	}

	defer in.Close()

	_, err = io.Copy(out, in)
	if err != nil {
		return err
	}

	return nil
}

func startScreenShareServer() {
	shr.StartScreenShareServer()
}

func main() {
	startScreenShareServer()
	listener, err := net.Listen("tcp", "192.168.45.69:6969")
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println("Server Online")
	go broadcast()

	for {
		conn, err := listener.Accept()
		if err != nil {
			log.Print(err)
			continue
		}

		buffer := make([]byte, 1024)
		_, er := conn.Read(buffer)
		if er != nil && err != io.EOF {
			log.Fatal(err)
		}
		cleanBuff := bytes.Trim(buffer, "\x00")
		user := User{Name: strings.Trim(string(cleanBuff), "\n"), Address: conn.RemoteAddr().String(), Connection: &conn}

		go handleConnection(conn, user)
	}
}
