package server

import (
	"context"
	"fmt"
	"io"
	"log"
	"net"
	"os"
	"sync"
	"time"

	"chat/pkg/kasugai"

	"github.com/grpc-ecosystem/go-grpc-middleware/ratelimit"
	"github.com/grpc-ecosystem/go-grpc-middleware/v2/interceptors/auth"
	"github.com/grpc-ecosystem/go-grpc-middleware/v2/interceptors/logging"
	"github.com/grpc-ecosystem/go-grpc-middleware/v2/interceptors/recovery"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/status"
)

const chunkSize = 64 * 1024 // 64 KB, adjust as needed

type Client struct {
	ClientInfo    *kasugai.User
	HeartbeatChan chan bool
	Messages      []*kasugai.Message
	Broadcast     []kasugai.ChatService_ReceiveMessagesServer
	VideoStreams  []*kasugai.VideoStream
	ScreenShares  []*kasugai.ScreenShare
	FileChunks    map[string][]*kasugai.FileChunk
	FileMetadata  map[string]*kasugai.FileMetadata
}

type Server struct {
	kasugai.UnimplementedChatServiceServer
	kasugai.UnimplementedFileTransferServiceServer
	mu            sync.Mutex
	Clients       map[string]Client
	clientTimeout time.Duration
}

type rateLimiter struct {
}

func (rl *rateLimiter) Limit() bool {
	// Return true if the request should be limited (i.e., denied), false otherwise.
	// Use your internal rate limiter logic here.
	return true
}

func StartServer(address string) error {
	lis, err := net.Listen("tcp", address)
	if err != nil {
		log.Fatalf("failed to listen: %v", err)
		return err
	}

	server := &Server{
		Clients:       make(map[string]Client),
		clientTimeout: 2 * time.Minute,
	}

	logger := log.New(os.Stderr, "", log.Ldate|log.Ltime|log.Lshortfile)

	opts := []logging.Option{
		logging.WithLogOnEvents(logging.StartCall, logging.FinishCall),
		logging.WithLevels(logging.DefaultServerCodeToLevel),
	}

	// recovery options
	recoveryOpt := recovery.WithRecoveryHandler(func(p interface{}) (err error) {
		logger.Printf("Panic occurred: %v", p) // Log the panic
		return status.Errorf(codes.Internal, "An internal error occurred")
	})

	s := grpc.NewServer(
		grpc.ChainUnaryInterceptor(
			// auth.UnaryServerInterceptor(authFunc),
			// ratelimit.UnaryServerInterceptor(limiter),
			recovery.UnaryServerInterceptor(recoveryOpt),
			logging.UnaryServerInterceptor(InterceptorLogger(logger), opts...),
		),
		grpc.ChainStreamInterceptor(
			// auth.StreamServerInterceptor(authFunc),
			// ratelimit.StreamServerInterceptor(limiter),
			recovery.StreamServerInterceptor(recoveryOpt),
			logging.StreamServerInterceptor(InterceptorLogger(logger), opts...),
		),
	)

	kasugai.RegisterChatServiceServer(s, server)
	kasugai.RegisterFileTransferServiceServer(s, server)
	if err := s.Serve(lis); err != nil {
		log.Fatalf("failed to serve: %v", err)
		return err
	}
	return nil
}

func StartServerWithTLS(address string) error {
	// Load server cert and key
	creds, err := credentials.NewServerTLSFromFile("cert.pem", "key.pem")
	if err != nil {
		log.Fatalf("Failed to setup TLS: %v", err)
		return err
	}
	log.Println("TLS setup successful.")
	lis, err := net.Listen("tcp", address) //:50051
	if err != nil {
		log.Fatalf("failed to listen: %v", err)
		return err
	}

	server := &Server{
		Clients:       make(map[string]Client),
		clientTimeout: 2 * time.Minute,
	}

	logger := log.New(os.Stderr, "", log.Ldate|log.Ltime|log.Lshortfile)

	opts := []logging.Option{
		logging.WithLogOnEvents(logging.StartCall, logging.FinishCall),
		// Add any other option if needed.
	}

	limiter := &rateLimiter{
		// initialize internal rate limiter here
	}

	// recovery options
	recoveryOpt := recovery.WithRecoveryHandler(func(p interface{}) (err error) {
		// Custom logic, for example, return a custom error message to the client
		return status.Errorf(codes.Internal, "An internal error occurred.")
	})

	s := grpc.NewServer(
		grpc.Creds(creds),
		grpc.ChainUnaryInterceptor(
			auth.UnaryServerInterceptor(authFunc),
			ratelimit.UnaryServerInterceptor(limiter),
			recovery.UnaryServerInterceptor(recoveryOpt),
			logging.UnaryServerInterceptor(InterceptorLogger(logger), opts...),
		),
		grpc.ChainStreamInterceptor(
			auth.StreamServerInterceptor(authFunc),
			ratelimit.StreamServerInterceptor(limiter),
			recovery.StreamServerInterceptor(recoveryOpt),
			logging.StreamServerInterceptor(InterceptorLogger(logger), opts...),
		),
	)

	kasugai.RegisterChatServiceServer(s, server)
	kasugai.RegisterFileTransferServiceServer(s, server)
	if err := s.Serve(lis); err != nil {
		log.Fatalf("failed to serve: %v", err)
		return err
	}
	return nil
}

// InterceptorLogger adapts standard Go logger to interceptor logger.
func InterceptorLogger(l *log.Logger) logging.Logger {
	return logging.LoggerFunc(func(_ context.Context, lvl logging.Level, msg string, fields ...any) {
		switch lvl {
		case logging.LevelDebug:
			l.Printf("[DEBUG] %s - %v", msg, fields)
		case logging.LevelInfo:
			l.Printf("[INFO] %s - %v", msg, fields)
		case logging.LevelWarn:
			l.Printf("[WARN] %s - %v", msg, fields)
		case logging.LevelError:
			l.Printf("[ERROR] %s - %v", msg, fields)
		default:
			l.Printf("[UNKNOWN] %s - %v", msg, fields)
		}
	})
}

// authentication
func authFunc(ctx context.Context) (context.Context, error) {
	// Extract the token from the request's metadata
	token, err := auth.AuthFromMD(ctx, "bearer")
	if err != nil {
		return nil, status.Errorf(codes.Unauthenticated, "no token found in metadata")
	}

	// Validate the token (or call actual authentication service or logic here)
	if token != "secret-token" {
		return nil, status.Errorf(codes.Unauthenticated, "invalid token")
	}

	// If authenticated, return the context (possibly enriched with user information or other data)
	return ctx, nil
}

// RegisterClient allows clients to register themselves with the server.
func (s *Server) RegisterClient(ctx context.Context, req *kasugai.User) (*kasugai.Ack, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	if _, exists := s.Clients[req.Uuid.Uuid]; exists { // Accessing the UUID from User
		return &kasugai.Ack{
			Success: false,
			Message: fmt.Sprintf("Client with ID %s already exists", req.Uuid),
		}, nil
	}

	client := Client{
		ClientInfo: &kasugai.User{
			Uuid: req.Uuid,
			Name: req.Name,
		},
		HeartbeatChan: make(chan bool),
		Messages:      make([]*kasugai.Message, 0),
		Broadcast:     make([]kasugai.ChatService_ReceiveMessagesServer, 0),
		VideoStreams:  make([]*kasugai.VideoStream, 0),
		ScreenShares:  make([]*kasugai.ScreenShare, 0),
		FileChunks:    make(map[string][]*kasugai.FileChunk),
		FileMetadata:  make(map[string]*kasugai.FileMetadata),
	}
	s.Clients[req.Uuid.Uuid] = client

	//go s.monitorClientHeartbeat(req.Uuid.Uuid)
	return &kasugai.Ack{Success: true, Message: "Registered"}, nil
}

// func (s *Server) SendHeartbeat(ctx context.Context, req *kasugai.Heartbeat) (*kasugai.Ack, error) {
// 	s.mu.Lock()
// 	defer s.mu.Unlock()

// 	client, exists := s.Clients[req.ClientId]
// 	if exists {
// 		client.HeartbeatChan <- true
// 		log.Printf("Received heartbeat from client ID: %s", req.ClientId)
// 		return &kasugai.Ack{Success: true, Message: "OK"}, nil
// 	}
// 	return &kasugai.Ack{Success: false, Message: "Offline"}, nil
// }

// func (s *Server) monitorClientHeartbeat(clientID string) {
// 	client, exists := s.Clients[clientID]
// 	if !exists {
// 		return
// 	}

// 	for {
// 		select {
// 		case <-time.After(s.clientTimeout): // Note: Assuming you have clientTimeout as part of your server structure.
// 			s.mu.Lock()
// 			delete(s.Clients, clientID)
// 			s.mu.Unlock()
// 			log.Printf("Client %s has dropped off", clientID)
// 			return
// 		case <-client.HeartbeatChan:
// 			// Reset the timer when we receive a heartbeat
// 			continue
// 		}
// 	}
// }

func (s *Server) SendMessage(ctx context.Context, req *kasugai.Message) (*kasugai.Ack, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	senderID := req.SenderId
	log.Printf("Received message from sender: %s", senderID)

	// Check if the sender is a registered client
	senderClient, senderExists := s.Clients[senderID]
	if !senderExists {
		log.Printf("Sender client not found: %s", senderID)
		return &kasugai.Ack{
			Success: false,
			Message: "Sender Client Not Found",
		}, nil
	}

	// Store the message in the sender's client messages
	senderClient.Messages = append(senderClient.Messages, req)

	// Check if recipientId is set; if not, broadcast the message to all clients
	if req.RecipientId == "" {
		log.Printf("Broadcasting message from sender: %s", senderID)
		for clientID, client := range s.Clients {
			if clientID != senderID { // Skip the sender
				log.Printf("Broadcasting to client: %s", clientID)
				for _, stream := range client.Broadcast {
					if err := stream.Send(req); err != nil {
						log.Printf("Failed to send message to client %s: %v", clientID, err)
					} else {
						log.Printf("Message sent to client %s", clientID)
					}
				}
			}
		}
		log.Printf("Broadcast completed for sender: %s", senderID)
	} else {
		// Direct message to a specific recipient
		recipientClient, recipientExists := s.Clients[req.RecipientId]
		if !recipientExists {
			log.Printf("Recipient client not found: %s", req.RecipientId)
			return &kasugai.Ack{
				Success: false,
				Message: "Recipient Client Not Found",
			}, nil
		}

		// Send the message to the recipient's active streams
		for _, stream := range recipientClient.Broadcast {
			log.Printf("Sending direct message to recipient: %s", req.RecipientId)
			if err := stream.Send(req); err != nil {
				log.Printf("Failed to send message to recipient %s: %v", req.RecipientId, err)
				return &kasugai.Ack{
					Success: false,
					Message: "Failed to send message to recipient",
				}, nil
			}
		}
		log.Printf("Direct message successfully sent to recipient: %s", req.RecipientId)
	}

	return &kasugai.Ack{Success: true, Message: "Message sent successfully"}, nil
}

func (s *Server) ReceiveMessages(req *kasugai.Id, stream kasugai.ChatService_ReceiveMessagesServer) error {
	clientID := req.Uuid

	s.mu.Lock()
	client, ok := s.Clients[clientID]
	if !ok {
		s.mu.Unlock()
		log.Printf("Client not found for receiving messages: %s", clientID)
		return status.Errorf(codes.NotFound, "Client Not Found")
	}

	// Register the client's stream to receive messages
	client.Broadcast = append(client.Broadcast, stream)
	log.Printf("Client %s connected to message stream", clientID)
	s.mu.Unlock()

	// Continuously keep the stream open until the client disconnects
	for {
		select {
		case <-stream.Context().Done():
			// Client has disconnected, remove the stream
			log.Printf("Client %s disconnected from message stream", clientID)
			s.mu.Lock()
			var updatedStreams []kasugai.ChatService_ReceiveMessagesServer
			for _, msgStream := range client.Broadcast {
				if msgStream != stream {
					updatedStreams = append(updatedStreams, msgStream)
				}
			}
			client.Broadcast = updatedStreams
			s.mu.Unlock()
			return nil
		default:
			// Avoid tight loop
			time.Sleep(100 * time.Millisecond)
		}
	}
}

func (s *Server) StartVideoStream(stream kasugai.ChatService_StartVideoStreamServer) error {
	for {
		videoStream, err := stream.Recv()
		if err == io.EOF {
			return stream.SendAndClose(&kasugai.Ack{Success: true})
		}
		if err != nil {
			return err
		}

		clientID := videoStream.StreamId
		s.mu.Lock()
		client, ok := s.Clients[clientID.Uuid]
		if !ok {
			s.mu.Unlock()
			return status.Errorf(codes.NotFound, "Client Not Found")
		}

		client.VideoStreams = append(client.VideoStreams, videoStream)
		s.mu.Unlock()
	}
}

func (s *Server) WatchVideoStream(req *kasugai.Id, stream kasugai.ChatService_WatchVideoStreamServer) error {
	s.mu.Lock()
	client, ok := s.Clients[req.Uuid]
	s.mu.Unlock()

	if !ok {
		return status.Errorf(codes.NotFound, "Client Not Found")
	}

	for _, videoStream := range client.VideoStreams {
		if err := stream.Send(videoStream); err != nil {
			return err
		}
	}

	return nil
}

func (s *Server) StartScreenShare(stream kasugai.ChatService_StartScreenShareServer) error {
	for {
		screenShare, err := stream.Recv()
		if err == io.EOF {
			return stream.SendAndClose(&kasugai.Ack{Success: true})
		}
		if err != nil {
			return err
		}

		clientID := screenShare.StreamId.Uuid
		s.mu.Lock()
		client, ok := s.Clients[clientID]
		if !ok {
			s.mu.Unlock()
			return status.Errorf(codes.NotFound, "Client Not Found")
		}

		client.ScreenShares = append(client.ScreenShares, screenShare)
		s.mu.Unlock()
	}
}

func (s *Server) WatchScreenShare(req *kasugai.Id, stream kasugai.ChatService_WatchScreenShareServer) error {
	s.mu.Lock()
	client, ok := s.Clients[req.Uuid]
	s.mu.Unlock()

	if !ok {
		return status.Errorf(codes.NotFound, "Client Not Found")
	}

	for _, screenShare := range client.ScreenShares {
		if err := stream.Send(screenShare); err != nil {
			return err
		}
	}

	return nil
}

func (s *Server) ReceiveFileMetadata(ctx context.Context, info *kasugai.Id) (*kasugai.FileMetadata, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	client, ok := s.Clients[info.Uuid]
	if !ok {
		return nil, status.Errorf(codes.NotFound, "Client Not Found")
	}
	metadata, ok := client.FileMetadata[info.Uuid]
	if !ok {
		return nil, status.Errorf(codes.NotFound, "Metadata Not Found")
	}
	return metadata, nil
}

func (s *Server) ReceiveFileChunk(req *kasugai.Id, stream kasugai.FileTransferService_ReceiveFileChunkServer) error {
	clientID := req.Uuid

	s.mu.Lock()
	client, ok := s.Clients[clientID]
	if !ok {
		s.mu.Unlock()
		return status.Errorf(codes.NotFound, "Client Not Found")
	}

	chunks, ok := client.FileChunks[clientID]
	if !ok {
		s.mu.Unlock()
		return status.Errorf(codes.NotFound, "File Not Found")
	}
	s.mu.Unlock()

	for _, chunk := range chunks {
		if err := stream.Send(chunk); err != nil {
			return err
		}
	}
	return nil
}

func (s *Server) SendFileMetadata(ctx context.Context, metadata *kasugai.FileMetadata) (*kasugai.Ack, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	client, ok := s.Clients[metadata.FileId.Uuid]
	if !ok {
		// If the client doesn't exist yet, we might need to create one.
		// You can also return an error instead if that's the desired behavior.
		client = Client{
			FileChunks:   make(map[string][]*kasugai.FileChunk),
			FileMetadata: make(map[string]*kasugai.FileMetadata),
		}
		s.Clients[metadata.FileId.Uuid] = client
	}
	client.FileMetadata[metadata.FileId.Uuid] = metadata
	return &kasugai.Ack{Success: true}, nil
}

func (s *Server) SendFileChunk(ctx context.Context, chunk *kasugai.FileChunk) (*kasugai.Ack, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	client, ok := s.Clients[chunk.FileId.Uuid]
	if !ok {
		// If the client doesn't exist yet, we might need to create one.
		// You can also return an error instead if that's the desired behavior.
		client = Client{
			FileChunks:   make(map[string][]*kasugai.FileChunk),
			FileMetadata: make(map[string]*kasugai.FileMetadata),
		}
		s.Clients[chunk.FileId.Uuid] = client
	}
	client.FileChunks[chunk.FileId.Uuid] = append(client.FileChunks[chunk.FileId.Uuid], chunk)
	return &kasugai.Ack{Success: true}, nil
}

func (s *Server) UploadFileToServer(ctx context.Context, chunk *kasugai.FileChunk) (*kasugai.Ack, error) {
	return s.SendFileChunk(ctx, chunk)
}

func (s *Server) DownloadFileFromServer(req *kasugai.Id, stream kasugai.FileTransferService_DownloadFileFromServerServer) error {
	return s.ReceiveFileChunk(req, stream)
}

func (s *Server) ListRegisteredClients(ctx context.Context, req *kasugai.ActiveUsersRequest) (*kasugai.ActiveUsersList, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	var users []*kasugai.User
	for _, client := range s.Clients {
		users = append(users, client.ClientInfo)
	}

	return &kasugai.ActiveUsersList{Users: users}, nil
}
