package clienthandler

import (
	"fmt"
	"net"
)

type User struct {
	Message     string   `json:"message"`
	Name        string   `json:"name"`
	Connection  net.Conn `json:"connection"`
	Address     string   `json:"address"`
	IsConnected bool     `json:"isconnected"`
	WorkingDir  string
}

func (u *User) ClientWriter(ch <-chan string) {
	for msg := range ch {
		fmt.Fprintln(u.Connection, msg)
		fmt.Printf("message sent => %v\n", msg)
	}
}
