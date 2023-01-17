package grpc

import (
	"fmt"
	"io"
)

type UserObj struct {
	user        *User
	conn        Broadcast_ChatStreamClient
	send        chan *MessageResponse
	quit        chan struct{}
	IsConnected bool
	WorkingDir  string
}

func NewUser(conn Broadcast_ChatStreamClient, usr *User) *UserObj {
	u := &UserObj{
		user: usr,
		conn: conn,
		send: make(chan *MessageResponse),
		quit: make(chan struct{}),
	}
	go u.start()
	return u
}

func (u *UserObj) SendMsg(msg *MessageResponse) {
	defer func() {
		// Ignore any errors about sending on a closed channel
		recover()
	}()
	u.send <- msg
}

func (u *UserObj) start() {
	running := true
	for running {
		select {
		case msg := <-u.send:
			u.conn.SendMsg(msg) // Ignoring the error, they just don't get this message.
		case <-u.quit:
			running = false
		}
	}
}

func (u *UserObj) Close() error {
	close(u.quit)
	close(u.send)
	return nil
}

func (u *UserObj) GetMessages(broadcast chan<- *MessageResponse) error {
	for {
		msg, err := u.conn.Recv()
		if err == io.EOF {
			u.Close()
			return nil
		} else if err != nil {
			u.Close()
			return err
		}
		go func(msg *MessageResponse) {
			select {
			case broadcast <- msg:
				fmt.Println(msg)
			case <-u.quit:
			}
		}(msg)
	}
}
