package server

import (
	"bytes"
	"context"
	"fmt"
	"image/png"
	"io"
	"net"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"

	"chat/internal/screenshare"
	"chat/pkg/kasugai"
	"chat/pkg/stdlog"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/emptypb"
	"google.golang.org/protobuf/types/known/timestamppb"
)

// Server struct holds all the clients and rooms information.
type Server struct {
	kasugai.UnimplementedUserServiceServer
	kasugai.UnimplementedRoomServiceServer
	kasugai.UnimplementedChatServiceServer
	kasugai.UnimplementedMediaServiceServer
	kasugai.UnimplementedFileTransferServiceServer

	mu                 sync.RWMutex
	clients            map[string]*kasugai.User
	rooms              map[string]*Room
	streams            map[string]chan *kasugai.TextMessage
	activeStreams      map[string]context.CancelFunc
	activeStreamsMutex sync.Mutex
	roomBuilder        *RoomBuilder
	logger             *stdlog.Logger
}

// NewServer initializes a new Server.
func NewServer(logger *stdlog.Logger) *Server {
	return &Server{
		clients:       make(map[string]*kasugai.User),
		rooms:         make(map[string]*Room),
		streams:       make(map[string]chan *kasugai.TextMessage),
		activeStreams: make(map[string]context.CancelFunc),
		roomBuilder:   NewRoomBuilder(),
		logger:        logger,
	}
}

// StartServer starts the gRPC server.
func StartServer(address string, logger *stdlog.Logger) error {
	lis, err := net.Listen("tcp", address)
	if err != nil {
		return fmt.Errorf("failed to listen: %v", err)
	}

	server := NewServer(logger)

	s := grpc.NewServer()
	kasugai.RegisterUserServiceServer(s, server)
	kasugai.RegisterRoomServiceServer(s, server)
	kasugai.RegisterChatServiceServer(s, server)
	kasugai.RegisterMediaServiceServer(s, server)
	kasugai.RegisterFileTransferServiceServer(s, server)

	logger.Info(fmt.Sprintf("gRPC server started on %s", address))
	return s.Serve(lis)
}

// UserService Methods

func (s *Server) RegisterUser(ctx context.Context, req *kasugai.User) (*kasugai.Ack, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	if req.Id == nil || req.Id.Uuid == "" {
		s.logger.Error(fmt.Sprintf("Failed user registration: Invalid user ID"))
		return &kasugai.Ack{Success: false, Message: "Invalid user ID"}, status.Error(codes.InvalidArgument, "Invalid user ID")
	}

	if _, exists := s.clients[req.Id.Uuid]; exists {
		s.logger.Warning(fmt.Sprintf("Failed user registration: User already exists (ID: %s)", req.Id.Uuid))
		return &kasugai.Ack{Success: false, Message: "User already exists"}, status.Error(codes.AlreadyExists, "User already exists")
	}

	s.clients[req.Id.Uuid] = req
	s.streams[req.Id.Uuid] = make(chan *kasugai.TextMessage, 100)

	s.logger.Info(fmt.Sprintf("User registered successfully (ID: %s, Name: %s)", req.Id.Uuid, req.Name))
	return &kasugai.Ack{Success: true, Message: "User registered"}, nil
}

func (s *Server) GetUserList(ctx context.Context, _ *emptypb.Empty) (*kasugai.UserList, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	users := make([]*kasugai.User, 0, len(s.clients))
	for _, user := range s.clients {
		users = append(users, user)
	}

	s.logger.Info(fmt.Sprintf("User list successfully requested"))
	return &kasugai.UserList{Users: users}, nil
}

func (s *Server) UpdateUserStatus(ctx context.Context, req *kasugai.User) (*kasugai.Ack, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	if req.Id == nil || req.Id.Uuid == "" {
		return nil, status.Error(codes.InvalidArgument, "Invalid user ID")
	}

	user, exists := s.clients[req.Id.Uuid]
	if !exists {
		return nil, status.Error(codes.NotFound, "User not found")
	}

	user.Status = req.Status
	return &kasugai.Ack{Success: true, Message: "User status updated"}, nil
}

func (s *Server) GetUserById(ctx context.Context, req *kasugai.Id) (*kasugai.User, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	user, exists := s.clients[req.Uuid]
	if !exists {
		return nil, status.Error(codes.NotFound, "User not found")
	}

	return user, nil
}

// RoomService Methods

func (s *Server) CreateRoom(ctx context.Context, req *kasugai.Room) (*kasugai.Ack, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	if req.Id == nil || req.Id.Uuid == "" {
		return nil, status.Error(codes.InvalidArgument, "Invalid room ID")
	}

	if _, exists := s.rooms[req.Id.Uuid]; exists {
		return nil, status.Error(codes.AlreadyExists, "Room already exists")
	}

	creator, exists := s.clients[req.CreatorId.Uuid]
	if !exists {
		return nil, status.Errorf(codes.NotFound, "Creator not found")
	}

	room, err := s.roomBuilder.
		WithName(req.Name).
		WithType(RoomType(req.Type)).
		WithCreator(creator).
		Build()

	if err != nil {
		return nil, status.Errorf(codes.InvalidArgument, err.Error())
	}

	s.rooms[room.ID] = room

	s.logger.Info(fmt.Sprintf("Room created: %s (Type: %v)", room.ID, room.Type))

	return &kasugai.Ack{Success: true, Message: "Room created"}, nil
}

func (s *Server) JoinRoom(ctx context.Context, req *kasugai.Id) (*kasugai.Ack, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	userID, err := FromContext(ctx)
	if err != nil {
		return nil, err
	}

	room, ok := s.rooms[req.Uuid]
	if !ok {
		return nil, status.Error(codes.NotFound, "Room not found")
	}

	for _, participants := range room.Participants {
		if participants.User.Id.Uuid == userID {
			return &kasugai.Ack{Success: true, Message: "User already in the room"}, nil
		}
	}

	room.Participants[userID] = &Participant{User: s.clients[userID], Role: RoleParticipant}
	return &kasugai.Ack{Success: true, Message: "User joined room"}, nil
}

func FromContext(ctx context.Context) (string, error) {
	userID, ok := ctx.Value("userID").(string)
	if !ok || userID == "" {
		return "", status.Error(codes.Unauthenticated, "User ID not found in context")
	}
	return userID, nil
}

func (s *Server) LeaveRoom(ctx context.Context, req *kasugai.Id) (*kasugai.Ack, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	room, ok := s.rooms[req.Uuid]
	if !ok {
		return nil, status.Error(codes.NotFound, "Room not found")
	}

	user, err := FromContext(ctx)
	if err != nil {
		return nil, status.Error(codes.NotFound, "Room not found")
	}

	delete(room.Participants, user)

	return nil, status.Error(codes.NotFound, "User not in room")
}

func (s *Server) GetRoomParticipants(ctx context.Context, req *kasugai.Id) (*kasugai.RoomParticipants, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	room, ok := s.rooms[req.Uuid]
	if !ok {
		return nil, status.Error(codes.NotFound, "Room not found")
	}

	participants := make([]*kasugai.User, 0, len(room.Participants))
	for _, participant := range room.Participants {
		if user, exists := s.clients[participant.User.Id.Uuid]; exists {
			participants = append(participants, user)
		}
	}

	return &kasugai.RoomParticipants{
		RoomId:       req,
		Participants: participants,
	}, nil
}

// ChatService Methods

func (s *Server) SendTextMessage(ctx context.Context, req *kasugai.TextMessage) (*kasugai.Ack, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	if req.RecipientId == nil || req.RecipientId.Uuid == "" {
		s.logger.Error("Failed to send message: Invalid recipient ID")
		return nil, status.Error(codes.InvalidArgument, "Invalid recipient ID")
	}

	room, ok := s.rooms[req.RecipientId.Uuid]
	if !ok {
		s.logger.Warning(fmt.Sprintf("Failed to send message: Room not found (ID: %s)", req.RecipientId.Uuid))
		return nil, status.Error(codes.NotFound, "Room not found")
	}

	req.Timestamp = timestamppb.Now()

	// Broadcast to all participants in the room
	for _, participant := range room.Participants {
		if participant.User.Id.Uuid != req.SenderId.Uuid {
			select {
			case participant.DirectChannel <- &RoomContent{
				Type:      TextMessage,
				SenderId:  req.SenderId.Uuid,
				Payload:   req,
				Timestamp: req.Timestamp,
			}:
				s.logger.Info(fmt.Sprintf("Message sent in room %s (From: %s, Content: %s)", req.RecipientId.Uuid, req.SenderId.Uuid, req.Content))
			default:
				s.logger.Error(fmt.Sprintf("Failed to send message: Participant's message queue is full (ID: %s)", participant.User.Id.Uuid))
			}
		}
	}

	return &kasugai.Ack{Success: true, Message: "Message sent"}, nil
}

func (s *Server) ReceiveTextMessages(req *kasugai.Id, stream kasugai.ChatService_ReceiveTextMessagesServer) error {
	s.mu.RLock()
	room, ok := s.rooms[req.Uuid]
	s.mu.RUnlock()

	if !ok {
		return status.Error(codes.NotFound, "Room not found")
	}

	participant, ok := room.Participants[req.Uuid]
	if !ok {
		return status.Error(codes.NotFound, "User not in room")
	}

	for {
		select {
		case content := <-participant.DirectChannel:
			if content.Type != TextMessage {
				s.logger.Debug(fmt.Sprintf("Skipping non-text content for user %s: %v", req.Uuid, content.Type))
				continue
			}

			textMsg, ok := content.Payload.(*kasugai.TextMessage)
			if !ok {
				s.logger.Error(fmt.Sprintf("Failed to convert payload to TextMessage for user %s", req.Uuid))
				continue
			}

			if err := stream.Send(textMsg); err != nil {
				s.logger.Error(fmt.Sprintf("Error sending message to user %s: %v", req.Uuid, err))
				return err
			}
			s.logger.Debug(fmt.Sprintf("Sent message to user %s: %v", req.Uuid, textMsg))

		case <-stream.Context().Done():
			s.logger.Info(fmt.Sprintf("Stopped receiving messages for user %s in room %s", req.Uuid, room.ID))
			return nil
		}
	}
}

// FileTransferService Methods

func (s *Server) InitiateFileTransfer(ctx context.Context, req *kasugai.FileMetadata) (*kasugai.Ack, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	return nil, status.Error(codes.Unimplemented, "Method InitiateFileTransfer not implemented")
}

func (s *Server) TransferFileChunk(stream kasugai.FileTransferService_TransferFileChunkServer) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	return status.Error(codes.Unimplemented, "Method TransferFileChunk not implemented")
}

func (s *Server) ReceiveFileMetadata(ctx context.Context, req *kasugai.Id) (*kasugai.FileMetadata, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return nil, status.Error(codes.Unimplemented, "Method ReceiveFileChunks not implemented")
}

func (s *Server) ReceiveFileChunks(req *kasugai.Id, stream kasugai.FileTransferService_ReceiveFileChunksServer) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	return status.Error(codes.Unimplemented, "Method ReceiveFileChunks not implemented")
}

// MediaService Methods

func (s *Server) StartMediaStream(stream kasugai.MediaService_StartMediaStreamServer) error {
	var streamID string
	var mediaType kasugai.MediaType

	initialData, err := stream.Recv()
	if err != nil {
		s.logger.Error(fmt.Sprintf("Error receiving initial media stream data: %v", err))
		return err
	}

	streamID = initialData.Id.Uuid
	mediaType = initialData.Type
	s.logger.Info(fmt.Sprintf("New media stream started: %s, Type: %s", streamID, mediaType))

	s.mu.RLock()
	room, ok := s.rooms[initialData.Id.Uuid]
	s.mu.RUnlock()

	if !ok {
		return status.Error(codes.NotFound, "Room not found")
	}

	streamCtx, cancelFunc := context.WithCancel(stream.Context())

	s.activeStreamsMutex.Lock()
	s.activeStreams[streamID] = cancelFunc
	s.activeStreamsMutex.Unlock()

	defer func() {
		s.activeStreamsMutex.Lock()
		delete(s.activeStreams, streamID)
		s.activeStreamsMutex.Unlock()
	}()

	switch mediaType {
	case kasugai.MediaType_SCREEN:
		return s.handleScreenShare(streamCtx, stream, initialData, room)
	case kasugai.MediaType_AUDIO:
		return s.handleAudioStream(streamCtx, stream, initialData, room)
	default:
		s.logger.Warning(fmt.Sprintf("Unknown media type: %s", mediaType))
		return status.Errorf(codes.InvalidArgument, "Unknown media type: %s", mediaType)
	}
}

func (s *Server) EndMediaStream(ctx context.Context, req *kasugai.Id) (*kasugai.Ack, error) {
	s.activeStreamsMutex.Lock()
	defer s.activeStreamsMutex.Unlock()

	cancelFunc, exists := s.activeStreams[req.Uuid]
	if !exists {
		s.logger.Warning(fmt.Sprintf("Attempt to end non-existent stream: %s", req.Uuid))
		return &kasugai.Ack{
			Success: false,
			Message: "Stream not found",
		}, status.Error(codes.NotFound, "Stream not found")
	}

	// Cancel the stream
	cancelFunc()

	// Remove the stream from the active streams map
	delete(s.activeStreams, req.Uuid)

	s.logger.Info(fmt.Sprintf("Media stream ended: %s", req.Uuid))
	return &kasugai.Ack{
		Success: true,
		Message: "Stream ended successfully",
	}, nil
}

func (s *Server) ManageVoIPCall(stream kasugai.MediaService_ManageVoIPCallServer) error {
	return status.Error(codes.Unimplemented, "Method ManageVoIPCall not implemented")
}

func (s *Server) handleScreenShare(ctx context.Context, stream kasugai.MediaService_StartMediaStreamServer, initialData *kasugai.MediaStream, room *Room) error {
	s.logger.Info(fmt.Sprintf("Screen sharing started for user: %s", initialData.SenderId.Uuid))

	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()

	buf := new(bytes.Buffer)
	interrupt := make(chan os.Signal, 1)
	signal.Notify(interrupt, os.Interrupt, syscall.SIGTERM)

	for {
		select {
		case <-ticker.C:
			img, err := screenshare.CaptureDisplay(0)
			if err != nil {
				s.logger.Error(fmt.Sprintf("Error capturing display: %v", err))
				return status.Errorf(codes.Internal, "Failed to capture display: %v", err)
			}

			buf.Reset()
			if err := png.Encode(buf, img); err != nil {
				s.logger.Error(fmt.Sprintf("Error encoding image: %v", err))
				return status.Errorf(codes.Internal, "Failed to encode image: %v", err)
			}

			// Broadcast screen data to all participants in the room
			for _, participant := range room.Participants {
				if participant.User.Id.Uuid != initialData.SenderId.Uuid {
					// Send the captured screen through the gRPC stream
					if err := stream.Send(&kasugai.MediaStream{
						Id:        initialData.Id,
						SenderId:  initialData.SenderId,
						Type:      kasugai.MediaType_SCREEN,
						Data:      buf.Bytes(),
						Timestamp: timestamppb.Now(),
					}); err != nil {
						s.logger.Error(fmt.Sprintf("Error sending screen share data: %v", err))
						return err
					}
					s.logger.Debug(fmt.Sprintf("Sent screen update for user: %s, size: %d bytes", initialData.SenderId.Uuid, buf.Len()))
				}
			}

		case <-interrupt:
			s.logger.Info(fmt.Sprintf("Screen sharing interrupted for user: %s", initialData.SenderId.Uuid))
			return status.Error(codes.Canceled, "Screen sharing interrupted")

		case <-ctx.Done():
			s.logger.Info(fmt.Sprintf("Screen sharing stopped for user: %s", initialData.SenderId.Uuid))
			return ctx.Err()
		}
	}
}

func (s *Server) handleAudioStream(ctx context.Context, stream kasugai.MediaService_StartMediaStreamServer, initialData *kasugai.MediaStream, room *Room) error {
	// Implement audio streaming logic here
	// This is a placeholder and should be implemented based on our VoIP requirements
	s.logger.Info(fmt.Sprintf("Audio streaming started for user: %s", initialData.SenderId.Uuid))

	for {
		data, err := stream.Recv()
		if err == io.EOF {
			s.logger.Info(fmt.Sprintf("Audio stream ended for user: %s", initialData.SenderId.Uuid))
			return nil
		}
		if err != nil {
			s.logger.Error(fmt.Sprintf("Error receiving audio data: %v", err))
			return err
		}

		// Process and forward audio data here
		// For example, you might send it to other participants in a call
		s.logger.Debug(fmt.Sprintf("Received audio data from user: %s, size: %d bytes", initialData.SenderId.Uuid, len(data.Data)))

		// Send acknowledgment
		if err := stream.Send(&kasugai.MediaStream{
			Id:        initialData.Id,
			SenderId:  initialData.SenderId,
			Type:      kasugai.MediaType_AUDIO,
			Data:      []byte("ACK"),
			Timestamp: timestamppb.Now(),
		}); err != nil {
			s.logger.Error(fmt.Sprintf("Error sending audio ACK: %v", err))
			return err
		}

		// Check for stream context cancellation
		select {
		case <-ctx.Done():
			s.logger.Info(fmt.Sprintf("Audio streaming stopped for user: %s", initialData.SenderId.Uuid))
			return ctx.Err()
		default:
		}
	}
}
