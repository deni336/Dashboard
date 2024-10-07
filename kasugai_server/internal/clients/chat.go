package clients

import (
	"context"
	"fmt"
	"io"
	"time"

	"chat/pkg/kasugai"

	"google.golang.org/grpc"
	"google.golang.org/grpc/metadata"
)

type KasugaiClient struct {
	conn            *grpc.ClientConn
	userService     kasugai.UserServiceClient
	roomService     kasugai.RoomServiceClient
	chatService     kasugai.ChatServiceClient
	mediaService    kasugai.MediaServiceClient
	CurrentUser     *kasugai.User
	CurrentRoomID   *kasugai.Id
	stopScreenShare chan struct{}
}

func NewKasugaiClient(serverAddr string) (*KasugaiClient, error) {
	conn, err := grpc.Dial(serverAddr, grpc.WithInsecure())
	if err != nil {
		return nil, fmt.Errorf("failed to connect to server: %v", err)
	}

	return &KasugaiClient{
		conn:         conn,
		userService:  kasugai.NewUserServiceClient(conn),
		roomService:  kasugai.NewRoomServiceClient(conn),
		chatService:  kasugai.NewChatServiceClient(conn),
		mediaService: kasugai.NewMediaServiceClient(conn),
	}, nil
}

func (c *KasugaiClient) Close() {
	c.conn.Close()
}

func (c *KasugaiClient) RegisterUser(name string) error {
	user := &kasugai.User{
		Id:     &kasugai.Id{Uuid: generateUUID()},
		Name:   name,
		Status: kasugai.UserStatus_ONLINE,
	}

	ack, err := c.userService.RegisterUser(context.Background(), user)
	if err != nil {
		return fmt.Errorf("failed to register user: %v", err)
	}

	if !ack.Success {
		return fmt.Errorf("registration failed: %s", ack.Message)
	}

	c.CurrentUser = user
	return nil
}

func (c *KasugaiClient) CreateRoom(room *kasugai.Room, key string) (*kasugai.Id, error) {
	if c.CurrentUser == nil {
		return nil, fmt.Errorf("user not registered")
	}

	if key == "" {
		room.Key = "OPEN"
	}

	room.Key = key

	ack, err := c.roomService.CreateRoom(context.Background(), room)
	if err != nil {
		return nil, fmt.Errorf("failed to create room: %v", err)
	}

	if !ack.Success {
		return nil, fmt.Errorf("room creation failed: %s", ack.Message)
	}

	return &kasugai.Id{Uuid: ack.Message}, nil
}

func (c *KasugaiClient) JoinRoom(roomID *kasugai.Id) error {
	if c.CurrentUser == nil {
		return fmt.Errorf("user not registered")
	}

	ctx := metadata.NewOutgoingContext(context.Background(), metadata.New(map[string]string{
		"user": c.CurrentUser.Id.Uuid,
	}))

	ack, err := c.roomService.JoinRoom(ctx, roomID)
	if err != nil {
		return fmt.Errorf("failed to join room: %v", err)
	}

	if !ack.Success {
		return fmt.Errorf("joining room failed: %s", ack.Message)
	}

	c.CurrentRoomID = roomID
	return nil
}

func (c *KasugaiClient) LeaveRoom() error {
	if c.CurrentUser == nil || c.CurrentRoomID == nil {
		return fmt.Errorf("user not registered or not in a room")
	}

	ctx := metadata.NewOutgoingContext(context.Background(), metadata.New(map[string]string{
		"user": c.CurrentUser.Id.Uuid,
	}))

	ack, err := c.roomService.LeaveRoom(ctx, c.CurrentRoomID)
	if err != nil {
		return fmt.Errorf("failed to leave room: %v", err)
	}

	if !ack.Success {
		return fmt.Errorf("leaving room failed: %s", ack.Message)
	}

	c.CurrentRoomID = nil
	fmt.Println("Left room successfully:", ack.Message)
	return nil
}

func (c *KasugaiClient) SendTextMessage(content string) error {
	if c.CurrentUser == nil || c.CurrentRoomID == nil {
		return fmt.Errorf("user not registered or not in a room")
	}

	msg := &kasugai.TextMessage{
		Id:          &kasugai.Id{Uuid: generateUUID()},
		SenderId:    c.CurrentUser.Id,
		RecipientId: c.CurrentRoomID,
		Content:     content,
	}

	ack, err := c.chatService.SendTextMessage(context.Background(), msg)
	if err != nil {
		return fmt.Errorf("failed to send message: %v", err)
	}

	if !ack.Success {
		return fmt.Errorf("sending message failed: %s", ack.Message)
	}

	return nil
}

func (c *KasugaiClient) ReceiveTextMessages() error {
	if c.CurrentUser == nil || c.CurrentRoomID == nil {
		return fmt.Errorf("user not registered or not in a room")
	}

	ctx := metadata.NewOutgoingContext(context.Background(), metadata.New(map[string]string{
		"user": c.CurrentUser.Id.Uuid,
	}))

	stream, err := c.chatService.ReceiveTextMessages(ctx, c.CurrentRoomID)
	if err != nil {
		return fmt.Errorf("failed to start receiving messages: %v", err)
	}

	for {
		msg, err := stream.Recv()
		if err == io.EOF {
			return nil
		}
		if err != nil {
			return fmt.Errorf("error receiving message: %v", err)
		}

		fmt.Printf("Received message from %s: %s\n", msg.SenderId.Uuid, msg.Content)
	}
}

func generateUUID() string {
	return fmt.Sprintf("user-%d", time.Now().UnixNano())
}
