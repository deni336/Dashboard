package server

import (
	"context"
	"fmt"
	"net"
	"sync"
	"time"

	"chat/pkg/datastore"
	"chat/pkg/kasugai"
	"chat/pkg/stdlog"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/reflection"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/emptypb"
	"google.golang.org/protobuf/types/known/timestamppb"
)

// Server struct holds all the clients and rooms information.
type Server struct {
	kasugai.UnimplementedUserServiceServer
	kasugai.UnimplementedRoomServiceServer
	kasugai.UnimplementedChatServiceServer

	mu                 sync.RWMutex
	clients            map[string]*kasugai.User
	rooms              map[string]*Room
	streams            map[string]chan *kasugai.TextMessage
	activeStreams      map[string]context.CancelFunc
	activeStreamsMutex sync.Mutex
	roomBuilder        *RoomBuilder
	dataStore          *datastore.DataStore
	grpcServer         *grpc.Server
	logger             *stdlog.Logger
}

// NewServer initializes a new Server.
func NewServer(logger *stdlog.Logger, ds *datastore.DataStore) *Server {
	return &Server{
		clients:       make(map[string]*kasugai.User),
		rooms:         make(map[string]*Room),
		streams:       make(map[string]chan *kasugai.TextMessage),
		activeStreams: make(map[string]context.CancelFunc),
		roomBuilder:   NewRoomBuilder(),
		dataStore:     ds,
		logger:        logger,
	}
}

// Start starts the gRPC server.
func (s *Server) Start(address string) error {
	lis, err := net.Listen("tcp", address)
	if err != nil {
		return fmt.Errorf("failed to listen: %v", err)
	}

	s.grpcServer = grpc.NewServer()

	kasugai.RegisterUserServiceServer(s.grpcServer, s.UnimplementedUserServiceServer)
	kasugai.RegisterRoomServiceServer(s.grpcServer, s.UnimplementedRoomServiceServer)
	kasugai.RegisterChatServiceServer(s.grpcServer, s.UnimplementedChatServiceServer)

	// Register reflection service on gRPC server
	reflection.Register(s.grpcServer)

	s.logger.Info(fmt.Sprintf("Chat gRPC server started on: %s", address))
	// Start serving
	if err := s.grpcServer.Serve(lis); err != nil {
		return fmt.Errorf("failed to serve: %v", err)
	}
	return nil
}

// Stop stops the gRPC server
func (s *Server) Stop() {
	s.logger.Info("Stopping server...")
	stopped := make(chan struct{})
	go func() {
		s.grpcServer.GracefulStop()
		close(stopped)
	}()

	t := time.NewTimer(10 * time.Second)
	select {
	case <-stopped:
		s.logger.Info("Server stopped gracefully")
	case <-t.C:
		s.logger.Warning("Server stop timeout, forcing shutdown")
		s.grpcServer.Stop()
	}
	t.Stop()
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
	s.streams[req.Id.Uuid] = make(chan *kasugai.TextMessage, 1024)

	// Add to datastore
	s.dataStore.AddUser(req)

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

	// Could do this instead
	//list, exists := s.dataStore.GetUserList()
	//if !exists {
	//	return nil, status.Error(codes.NotFound, "User list not found")
	//}
	//return list, nil

	s.logger.Info(fmt.Sprintf("User list successfully requested"))
	return &kasugai.UserList{Users: users}, nil
}

func (s *Server) UpdateUserStatus(ctx context.Context, req *kasugai.User) (*kasugai.Ack, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	if req.Id == nil || req.Id.Uuid == "" {
		return &kasugai.Ack{Success: false, Message: "Invalid user id"}, status.Error(codes.InvalidArgument, "Invalid user ID")
	}

	user, exists := s.clients[req.Id.Uuid]
	if !exists {
		return &kasugai.Ack{Success: false, Message: "User not found"}, status.Error(codes.NotFound, "user not found")
	}

	// Update datastore user
	u, exists := s.dataStore.GetUser(req.Id.Uuid)
	if !exists {
		return &kasugai.Ack{Success: false, Message: "User not found"}, status.Error(codes.NotFound, "user not found")
	}
	u.Status = req.Status

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

	// using datastore instead
	//user, exists := s.dataStore.GetUser(req.Uuid)
	//if !exists {
	//	return nil, status.Error(codes.NotFound, "User not found")
	//}

	return user, nil
}

// RoomService Methods

func (s *Server) CreateRoom(ctx context.Context, req *kasugai.Room) (*kasugai.Ack, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	creator, exists := s.clients[req.CreatorId.Uuid]
	if !exists {
		return &kasugai.Ack{Success: false, Message: "Failed to build the room"}, status.Errorf(codes.NotFound, "Creator not found")
	}

	room, err := s.roomBuilder.
		WithName(req.Name).
		WithType(RoomType(req.Type)).
		WithCreator(creator).
		WithKey(req.Key).
		Build()

	if err != nil {
		return &kasugai.Ack{Success: false, Message: "Failed to build the room"}, status.Errorf(codes.InvalidArgument, err.Error())
	}

	// Add to datastore
	s.rooms[room.Channel.Id.Uuid] = room
	s.dataStore.AddRoom(room.Channel)

	s.logger.Info(fmt.Sprintf("Room created: %s (Type: %v)", room.Channel.Id, room.Channel.Type))

	return &kasugai.Ack{Success: true, Message: room.Channel.Id.Uuid}, nil
}

func (s *Server) JoinRoom(ctx context.Context, req *kasugai.Id) (*kasugai.Ack, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	md, ok := metadata.FromIncomingContext(ctx)
	if !ok {
		return &kasugai.Ack{Success: false, Message: "Failed to get metadata"}, status.Error(codes.InvalidArgument, "failed to get metadata")
	}

	// Get specific values from metadata
	userIDs := md.Get("user")
	if len(userIDs) == 0 {
		return &kasugai.Ack{Success: false, Message: "User ID not found in metadata"}, status.Error(codes.InvalidArgument, "user id not found in metadata")
	}
	userID := userIDs[0]

	roomKeys := md.Get("key")
	if len(roomKeys) == 0 {
		return &kasugai.Ack{Success: false, Message: "Room key not found in metadata"}, status.Error(codes.InvalidArgument, "room key not found in metadata")
	}
	roomKey := roomKeys[0]

	room, ok := s.rooms[req.Uuid]
	if !ok {
		return &kasugai.Ack{Success: false, Message: "Room not found"}, status.Error(codes.NotFound, "room not found")
	}

	if s.rooms[req.Uuid].key != roomKey {
		return &kasugai.Ack{Success: false, Message: "Invalid key"}, status.Error(codes.InvalidArgument, "this key does not fit the lock")
	}

	for _, participants := range room.Participants {
		if participants.User.Id.Uuid == userID {
			return &kasugai.Ack{Success: false, Message: "User already in the room"}, status.Error(codes.AlreadyExists, "already in the room")
		}
	}

	client := &Participant{
		User: s.clients[userID],
		Role: RoleParticipant,
	}

	if room.Channel.CreatorId.Uuid == userID {
		client.Role = RoleAdmin
	}

	// add to datastore room
	room.Participants[userID] = client
	s.dataStore.AddRoomParticipants(s.clients[userID], room.Channel.Id)

	s.logger.Info(fmt.Sprintf("User joined the channel: %s (Joined the room: %v | RoomID: %v)", s.clients[userID].Name, room.Channel.Name, room.Channel.Id))
	return &kasugai.Ack{Success: true, Message: "User joined room"}, nil
}

func (s *Server) LeaveRoom(ctx context.Context, req *kasugai.Id) (*kasugai.Ack, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	failMsg := &kasugai.Ack{Success: false, Message: "Failed to leave the room"}
	room, ok := s.rooms[req.Uuid]
	if !ok {
		return failMsg, status.Error(codes.NotFound, "Room not found")
	}

	md, ok := metadata.FromIncomingContext(ctx)
	if !ok {
		return failMsg, status.Error(codes.InvalidArgument, "Failed to get metadata")
	}

	userIDs := md.Get("user")
	if len(userIDs) == 0 {
		return failMsg, status.Error(codes.InvalidArgument, "User ID not found in metadata")
	}
	userID := userIDs[0]

	if room.Participants[userID] != nil {
		delete(room.Participants, userID)
		s.dataStore.RemoveParticipant(room.Channel.Id, s.clients[userID])
		// Cancel the stream context for this user in this room
		s.activeStreamsMutex.Lock()
		if cancelFunc, exists := s.activeStreams[userID+"-"+req.Uuid]; exists {
			cancelFunc()
			delete(s.activeStreams, userID+"-"+req.Uuid)
			// don't forget datastore
		}
		s.activeStreamsMutex.Unlock()
	} else {
		return failMsg, status.Error(codes.InvalidArgument, "User not found in room.")
	}

	s.logger.Info(fmt.Sprintf("User left the channel: %s (Left room: %v | RoomID: %v)", s.clients[userID].Name, room.Channel.Name, room.Channel.Id))
	return &kasugai.Ack{Success: true, Message: "Successfully left the chat room."}, nil
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

	// Could possibly do this
	// return s.dataStore.GetRoomParticipants(req)

	return &kasugai.RoomParticipants{
		RoomId:       req,
		Participants: participants,
	}, nil
}

func (s *Server) GetRoomList(ctx context.Context) (*kasugai.RoomList, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	roomList := &kasugai.RoomList{}

	if len(s.rooms) == 0 {
		return nil, status.Error(codes.NotFound, "Room list is empty")
	}

	for _, room := range s.rooms {
		roomList.Rooms = append(roomList.Rooms, room.Channel)
	}

	// Could return this
	//list, exists := s.dataStore.GetRoomList()
	//if !exists { return nil, status.Error(codes.NotFound, "no rooms found") }
	//return list, nil

	return roomList, nil
}

// ChatService Methods

func (s *Server) SendTextMessage(ctx context.Context, req *kasugai.TextMessage) (*kasugai.Ack, error) {
	s.mu.RLock()
	room, ok := s.rooms[req.RecipientId.Uuid]
	s.mu.RUnlock()

	if !ok {
		return &kasugai.Ack{Success: false, Message: "Room not found"}, status.Error(codes.NotFound, "Room not found")
	}

	content := &RoomContent{
		Type:      TextMessage,
		SenderId:  req.SenderId.Uuid,
		Payload:   req,
		Timestamp: timestamppb.Now(),
	}

	select {
	case room.Broadcast <- []*RoomContent{content}:
		s.logger.Info(fmt.Sprintf("Message broadcast in room %s (From: %s, Content: %s)", req.RecipientId.Uuid, req.SenderId.Uuid, req.Content))
	default:
		s.logger.Error(fmt.Sprintf("Failed to send message: Room broadcast channel is full (Room: %s)", req.RecipientId.Uuid))
		return &kasugai.Ack{Success: false, Message: "Room broadcast channel is full"}, status.Error(codes.ResourceExhausted, "Room broadcast channel is full")
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

	md, ok := metadata.FromIncomingContext(stream.Context())
	if !ok {
		return status.Error(codes.InvalidArgument, "Failed to get metadata")
	}

	userIDs := md.Get("user")
	if len(userIDs) == 0 {
		return status.Error(codes.InvalidArgument, "User ID not found in metadata")
	}
	userID := userIDs[0]

	// Create a new context with cancellation
	ctx, cancel := context.WithCancel(stream.Context())
	defer cancel()

	// Register the cancel function
	s.activeStreamsMutex.Lock()
	s.activeStreams[userID+"-"+req.Uuid] = cancel
	s.activeStreamsMutex.Unlock()

	// Ensure we remove the cancel function when we're done
	defer func() {
		s.activeStreamsMutex.Lock()
		delete(s.activeStreams, userID+"-"+req.Uuid)
		s.activeStreamsMutex.Unlock()
	}()

	for {
		select {
		case contents := <-room.Broadcast:
			for _, content := range contents {
				if content.Type != TextMessage {
					s.logger.Debug(fmt.Sprintf("Skipping non-text content in room %s: %v", req.Uuid, content.Type))
					continue
				}

				textMsg, ok := content.Payload.(*kasugai.TextMessage)
				if !ok {
					s.logger.Error(fmt.Sprintf("Failed to convert payload to TextMessage in room %s", req.Uuid))
					continue
				}

				if err := stream.Send(textMsg); err != nil {
					s.logger.Error(fmt.Sprintf("Error sending message to user %s in room %s: %v", userID, req.Uuid, err))
					return err
				}
				s.logger.Debug(fmt.Sprintf("Sent message to user %s in room %s: %v", userID, req.Uuid, textMsg))
			}

		case <-ctx.Done():
			s.logger.Info(fmt.Sprintf("Stopped receiving messages for user %s in room %s", userID, req.Uuid))
			return nil
		}
	}
}
