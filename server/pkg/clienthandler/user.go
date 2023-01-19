package clienthandler

import (
	pb "chat/pkg/kasugai"
	"fmt"
	"io"
)

type User struct {
	user        *pb.User
	conn        pb.Broadcast_ChatServiceServer
	send        chan *pb.MessageResponse
	quit        chan struct{}
	IsConnected bool
	WorkingDir  string
}

func NewUser(conn pb.Broadcast_ChatServiceServer, usr *pb.User) *User {
	u := &User{
		user: usr,
		conn: conn,
		send: make(chan *pb.MessageResponse),
		quit: make(chan struct{}),
	}
	go u.start()
	return u
}

func (u *User) SendMsg(msg *pb.MessageResponse) {
	defer func() {
		// Ignore any errors about sending on a closed channel
		recover()
	}()
	u.send <- msg
}

func (u *User) start() {
	running := true
	for running {
		select {
		case msg := <-u.send:
			u.conn.Send(msg) // Ignoring the error, they just don't get this message.
		case <-u.quit:
			running = false
		}
	}
}

func (u *User) Close() error {
	close(u.quit)
	close(u.send)
	return nil
}

func (u *User) GetMessages(broadcast chan<- *pb.MessageResponse) error {
	for {
		msg, err := u.conn.Recv()
		if err == io.EOF {
			u.Close()
			return nil
		} else if err != nil {
			u.Close()
			return err
		}
		go func(msg *pb.MessageResponse) {
			select {
			case broadcast <- msg:
				fmt.Println(msg)
			case <-u.quit:
			}
		}(msg)
	}
}
