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
	atv_usrs    ActiveUsers
}

func NewBroadcastServer() *Server {
	srv := &Server{
		bcast:    make(chan *pb.MessageResponse, 1000),
		quit:     make(chan struct{}),
		atv_usrs: *InitializeActiveUserList(),
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

func Run(addr *string) error {
	chatConn, err := net.Listen("tcp", *addr)
	if err != nil {
		fmt.Println(err)
		fmt.Println("Failed to start chat server")
		return err
	}

	s := grpc.NewServer()

	server := NewBroadcastServer()

	pb.RegisterBroadcastServer(s, server)

	fmt.Println("[SUCCESS] chat server online and listening on", *addr)
	if err := s.Serve(chatConn); err != nil {
		fmt.Println("failed to serve: ", err)
	}

	return nil
}

func (s *Server) ChatService(stream pb.Broadcast_ChatServiceServer) error {
	conn := NewUser(stream, &pb.User{})
	s.connLock.Lock()
	s.connections = append(s.connections, conn)
	s.connLock.Unlock()

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
