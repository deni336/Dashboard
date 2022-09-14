package main

import (
	"bufio"
	"bytes"
	storage "chat/FileStorage"
	shr "chat/ScreenShare"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"strings"
)

type client chan<- string // an outgoing message channel

type User struct {
	Msg         *client      `json:"msg"`
	Name        string       `json:"name"`
	Address     string       `json:"address"`
	Connection  *net.Conn    `json:"connection"`
	IsConnected bool         `json:"isconnected"`
	ListUsers   *ActiveUsers `json:"user-list"`
}

type ActiveUsers struct {
	Users []User `json:"Users"`
}

var (
	chatIP       = "192.168.45.10:6969"
	scrshareIP   = "192.168.45.10:7070"
	fileUploadIP = "192.168.45.10:8080"
	APIIP        = "192.168.45.10:1337"
	entering     = make(chan client)
	leaving      = make(chan client)
	messages     = make(chan string) // all incoming client messages
	active_users = ActiveUsers{}
)

func (au *ActiveUsers) Add(user User) {
	au.Users = append(au.Users, user)
}

func API(addr string) {
	http.HandleFunc("/active-users", updateActiveUsers)

	mux := http.DefaultServeMux.ServeHTTP
	logger := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		log.Println(r.RemoteAddr + " " + r.Method + " " + r.URL.String())
		mux(w, r)
	})

	e := http.ListenAndServe(addr, logger)
	if e != nil {
		log.Fatalln(e)
	}

	fmt.Println("API Online")
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
				fmt.Printf("message broadcasted => %v\n", msg)
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
		fmt.Printf("message sent => %v\n", msg)
	}
}

func handleConnection(conn net.Conn, user User) {
	ch := make(chan string) // outgoing client message
	user.IsConnected = true
	active_users.Add(user)
	user.ListUsers = &active_users

	go clientWriter(conn, ch)

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

	user.IsConnected = false
}

func parseBufferStr(cleanBuff []byte, addr string) (s string) {
	str := strings.Trim(string(cleanBuff), "\n")
	if str == "" {
		str = addr
	}
	return str
}

func readBuffer(conn net.Conn) []byte {
	buffer := make([]byte, 1024)
	_, err := conn.Read(buffer)
	if err != nil && err != io.EOF {
		log.Fatal(err)
	}
	return buffer
}

func startChatServer(addr string) net.Listener {
	chatConn, err := net.Listen("tcp", addr)
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println("Server Online")
	go broadcast()
	return chatConn
}

func updateActiveUsers(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case "GET":
		j, _ := json.Marshal(active_users)
		w.Write(j)
	case "POST":
	default:
		w.WriteHeader(http.StatusMethodNotAllowed)
		fmt.Fprintf(w, "No access")
	}
}

func main() {
	go shr.StartScreenShareServer(scrshareIP)
	go storage.HostUploader(fileUploadIP)
	go API(APIIP)
	chatConn := startChatServer(chatIP)

	for {
		conn, err := chatConn.Accept()
		if err != nil {
			log.Print(err)
			continue
		}

		cleanBuff := bytes.Trim(readBuffer(conn), "\x00")

		user := User{
			Name:       parseBufferStr(cleanBuff, conn.RemoteAddr().String()),
			Address:    conn.RemoteAddr().String(),
			Connection: &conn,
		}

		go handleConnection(conn, user)
	}
}
