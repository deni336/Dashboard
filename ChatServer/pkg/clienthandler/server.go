package clienthandler

import (
	pb "chat/pkg/kasugai"
	"fmt"
	"net"
	"sync"

	"google.golang.org/grpc"
)

type Server struct {
	pb.UnimplementedBroadcastServer
	bcast       chan *pb.MessageResponse
	connections []*User
	connLock    sync.Mutex
	quit        chan struct{}
}

func NewBroadcastServer() *Server {
	srv := &Server{
		bcast: make(chan *pb.MessageResponse, 1000),
		quit:  make(chan struct{}),
	}
	go srv.start()
	return srv
}

func (s *Server) Close() error {
	close(s.quit)
	return nil
}

func (s *Server) start() {
	running := true
	for running {
		select {
		case msg := <-s.bcast:
			s.connLock.Lock()
			for _, v := range s.connections {
				go v.SendMsg(msg)
			}
			s.connLock.Unlock()
		case <-s.quit:
			running = false
		}
	}
}

func Run(addr string) error {
	chatConn, err := net.Listen("tcp", addr)
	if err != nil {
		fmt.Println(err)
		fmt.Println("Failed to start chat server")
		return err
	}

	s := grpc.NewServer()

	server := NewBroadcastServer()

	pb.RegisterBroadcastServer(s, server)

	fmt.Println("[success!] chat server online and listening on", addr)
	if err := s.Serve(chatConn); err != nil {
		fmt.Println("failed to serve: ", err)
	}

	return nil
}

func (s *Server) ChatService(stream pb.Broadcast_ChatServiceServer) error {

	// response := &pb.MessageResponse{
	// 	Message:   "Bob is here bitches",
	// 	Timestamp: time.Now().Format("2006-01-02T15:04:05"),
	// }

	protoc_user := &pb.User{
		Name: "Bob",
	}

	conn := NewUser(stream, protoc_user)
	s.connLock.Lock()
	s.connections = append(s.connections, conn)
	s.connLock.Unlock()
	// atv_usrs.Add(user.Name, user)
	// fmt.Println("User created and added to active_user list")
	// fmt.Println(atv_usrs.ListUsers())
	err := conn.GetMessages(s.bcast)

	s.connLock.Lock()
	for i, v := range s.connections {
		if v == conn {
			s.connections = append(s.connections[:i], s.connections[i+1:]...)
		}
	}
	s.connLock.Unlock()

	return err
}
