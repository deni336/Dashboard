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

	"chat/pkg/command"
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

type AgentInfo struct {
	Agent    *c2.Agent
	Chan     chan bool
	Commands []*command.Command
}

type Server struct {
	kasugai.UnimplementedChatServiceServer
	kasugai.UnimplementedFileTransferServiceServer
	mu            sync.Mutex
	Agents        map[string]*AgentInfo
	videoStreams  map[string][]*kasugai.VideoStream
	screenShares  map[string][]*kasugai.ScreenShareChunk
	fileMetadatas map[string]*kasugai.FileMetadata
	fileChunks    map[string][]*kasugai.FileChunk
	agentTimeout  time.Duration
}

type rateLimiter struct {
	// your internal rate limiter
}

func (rl *rateLimiter) Limit() bool {
	// Return true if the request should be limited (i.e., denied), false otherwise.
	// Use your internal rate limiter logic here.
	return true
}

func StartServer(address string) error {
	lis, err := net.Listen("tcp", address) //:50051
	if err != nil {
		log.Fatalf("failed to listen: %v", err)
		return err
	}
	server := &Server{
		Agents:       make(map[string]*AgentInfo),
		agentTimeout: 2 * time.Minute,
		videoStreams: make(map[string][]*kasugai.VideoStream),
		screenShares: make(map[string][]*kasugai.ScreenShareChunk),
	}

	logger := log.New(os.Stderr, "", log.Ldate|log.Ltime|log.Lshortfile)

	opts := []logging.Option{
		logging.WithLogOnEvents(logging.StartCall, logging.FinishCall),
		// Add any other option if needed.
	}

	// recovery options
	recoveryOpt := recovery.WithRecoveryHandler(func(p interface{}) (err error) {
		// Custom logic, for example, return a custom error message to the client
		return status.Errorf(codes.Internal, "An internal error occurred.")
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
		Agents:       make(map[string]*AgentInfo),
		agentTimeout: 2 * time.Minute,
		videoStreams: make(map[string][]*kasugai.VideoStream),
		screenShares: make(map[string][]*kasugai.ScreenShareChunk),
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
			msg = fmt.Sprintf("DEBUG :%v", msg)
		case logging.LevelInfo:
			msg = fmt.Sprintf("INFO :%v", msg)
		case logging.LevelWarn:
			msg = fmt.Sprintf("WARN :%v", msg)
		case logging.LevelError:
			msg = fmt.Sprintf("ERROR :%v", msg)
		default:
			panic(fmt.Sprintf("unknown level %v", lvl))
		}
		l.Println(append([]any{"msg", msg}, fields...))
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

func (s *Server) SendMessage(ctx context.Context, message *kasugai.Message) (*kasugai.Ack, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.messages = append(s.messages, message)
	return &kasugai.Ack{Success: true}, nil
}

func (s *Server) ReceiveMessages(req *kasugai.Id, stream kasugai.ChatService_ReceiveMessagesServer) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, msg := range s.messages {
		if err := stream.Send(msg); err != nil {
			return err
		}
	}
	return nil
}

func (s *Server) StartVideoStream(stream kasugai.ChatService_StartVideoStreamServer) error {
	var streamData []*kasugai.VideoStream

	for {
		chunk, err := stream.Recv()
		if err == io.EOF {
			streamID := fmt.Sprintf("stream%d", len(s.videoStreams)+1)
			s.mu.Lock()
			s.videoStreams[streamID] = streamData
			s.mu.Unlock()
			return stream.SendAndClose(&kasugai.Ack{Success: true})
		}
		if err != nil {
			return err
		}
		streamData = append(streamData, chunk)
	}
}

func (s *Server) WatchVideoStream(req *kasugai.Id, stream kasugai.ChatService_WatchVideoStreamServer) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	streamData, ok := s.videoStreams[req.Uuid]
	if !ok {
		return status.Errorf(codes.NotFound, "Stream Not Found")
	}

	for _, chunk := range streamData {
		if err := stream.Send(chunk); err != nil {
			return err
		}
	}

	return nil
}

func (s *Server) StartScreenShare(stream kasugai.ChatService_StartScreenShareServer) error {
	var screenData []*kasugai.ScreenShareChunk

	for {
		chunk, err := stream.Recv()
		if err == io.EOF {
			shareID := fmt.Sprintf("share%d", len(s.screenShares)+1)
			s.mu.Lock()
			s.screenShares[shareID] = screenData
			s.mu.Unlock()
			return stream.SendAndClose(&kasugai.Ack{Success: true})
		}
		if err != nil {
			return err
		}
		screenData = append(screenData, chunk)
	}
}

func (s *Server) WatchScreenShare(req *kasugai.Id, stream kasugai.ChatService_WatchScreenShareServer) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	screenData, ok := s.screenShares[req.Uuid]
	if !ok {
		return status.Errorf(codes.NotFound, "Screen Share Not Found")
	}

	for _, chunk := range screenData {
		if err := stream.Send(chunk); err != nil {
			return err
		}
	}

	return nil
}

func (s *Server) ReceiveFileMetadata(ctx context.Context, id *kasugai.Id) (*kasugai.FileMetadata, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	metadata, ok := s.fileMetadatas[id.Uuid]
	if !ok {
		return nil, status.Errorf(codes.NotFound, "Metadata Not Found")
	}
	return metadata, nil
}

func (s *Server) ReceiveFileChunk(req *kasugai.Id, stream kasugai.FileTransferService_ReceiveFileChunkServer) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	chunks, ok := s.fileChunks[req.Uuid]
	if !ok {
		return status.Errorf(codes.NotFound, "File Not Found")
	}
	for _, chunk := range chunks {
		if err := stream.Send(chunk); err != nil {
			return err
		}
	}
	return nil
}

func (s *Server) SendFileMetadata(ctx context.Context, metadata *kasugai.FileMetadata) (*kasugai.Ack, error) {
	s.mu.Lock()
	s.fileMetadatas[metadata.Uuid] = metadata
	s.mu.Unlock()
	return &kasugai.Ack{Success: true}, nil
}

func (s *Server) SendFileChunk(ctx context.Context, chunk *kasugai.FileChunk) (*kasugai.Ack, error) {
	s.mu.Lock()
	s.fileChunks[chunk.Uuid] = append(s.fileChunks[chunk.Uuid], chunk)
	s.mu.Unlock()
	return &kasugai.Ack{Success: true}, nil
}

func (s *Server) UploadFileToServer(ctx context.Context, chunk *kasugai.FileChunk) (*kasugai.Ack, error) {
	return s.SendFileChunk(ctx, chunk)
}

func (s *Server) DownloadFileFromServer(req *kasugai.Id, stream kasugai.FileTransferService_DownloadFileFromServerServer) error {
	return s.ReceiveFileChunk(req, stream)
}

func (s *Server) Heartbeat(ctx context.Context, req *c2.HeartbeatRequest) (*c2.HeartbeatResponse, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	agentInfo, exists := s.Agents[req.AgentID]
	if exists {
		agentInfo.Chan <- true
		log.Printf("Received heartbeat from agent ID: %s", req.AgentID)
		return &c2.HeartbeatResponse{Status: "OK"}, nil
	}
	return &c2.HeartbeatResponse{Status: "Offline"}, nil
}

func (s *Server) monitorAgentHeartbeat(agentID string) {
	agentInfo, exists := s.Agents[agentID]
	if !exists {
		return
	}

	for {
		select {
		case <-time.After(s.agentTimeout):
			s.mu.Lock()
			delete(s.Agents, agentID)
			s.mu.Unlock()
			log.Printf("Agent %s has dropped off", agentID)
			return
		case <-agentInfo.Chan:
			// Reset the timer when we receive a heartbeat
			continue
		}
	}
}
