package main

// import (
// 	pb "chat/pkg/kasugai"
// 	"context"
// 	"fmt"
// 	"net"
// 	"time"

// 	"google.golang.org/grpc"
// )

// type Server struct {
// 	pb.UnimplementedBroadcastServer
// 	messages []*pb.MsgPayload
// 	// connLock sync.Mutex
// }

// func newServer() *Server {
// 	s := &Server{messages: make([]*pb.MsgPayload, 0)}
// 	return s
// }

// func Run(addr string) error {
// 	chatConn, err := net.Listen("tcp", addr)
// 	if err != nil {
// 		fmt.Println(err)
// 		fmt.Println("Failed to start chat server")
// 		return err
// 	}

// 	s := grpc.NewServer()

// 	//server, err := pb.NewBroadcastServer()

// 	pb.RegisterBroadcastServer(s, newServer().UnimplementedBroadcastServer)

// 	fmt.Println("[success!] chat server online and listening on", addr)
// 	if err := s.Serve(chatConn); err != nil {
// 		fmt.Println("failed to serve: ", err)
// 	}

// 	return nil
// }

// func (s *Server) ChatService(ctx context.Context, req *pb.MsgPayloadRequest) (*pb.MsgPayload, error) {
// 	fmt.Println("ChatService executed")
// 	return &pb.MsgPayload{
// 		Name:      "Bob",
// 		Message:   "Hello from bob",
// 		Timestamp: time.Now().Format("02-02-1992"),
// 	}, nil
// }

// func (s *Server) ChatStream(req *pb.MsgPayload, stream pb.Broadcast_ChatStreamServer) error {
// 	s.messages = append(s.messages, req)
// 	fmt.Println(req)
// 	for _, feature := range s.messages {
// 		fmt.Println(feature)
// 		if err := stream.Send(feature); err != nil {
// 			return err
// 		}
// 	}
// 	return nil
// }

// func main() {
// 	Run("localhost:6969")
// }
