package clients

import (
	"bytes"
	"context"
	"fmt"
	"image/png"
	"io"
	"log"
	"strings"
	"time"

	"chat/internal/screenshare"
	"chat/pkg/kasugai"

	"google.golang.org/grpc"
	"google.golang.org/grpc/metadata"
	"google.golang.org/protobuf/types/known/timestamppb"
)

type ScreenShareClient struct {
	conn         *grpc.ClientConn
	mediaService kasugai.MediaServiceClient
	currentUser  *kasugai.User
	currentRoom  *kasugai.Id
	stopShare    chan struct{}
}

func NewScreenShareClient(serverAddr string) (*ScreenShareClient, error) {
	conn, err := grpc.Dial(serverAddr, grpc.WithInsecure())
	if err != nil {
		return nil, fmt.Errorf("failed to connect to server: %v", err)
	}

	log.Printf("Connected to media server at %s", serverAddr)

	return &ScreenShareClient{
		conn:         conn,
		mediaService: kasugai.NewMediaServiceClient(conn),
		stopShare:    make(chan struct{}),
	}, nil
}

func (c *ScreenShareClient) Close() {
	if c.conn != nil {
		c.conn.Close()
		log.Println("Closed connection to media server")
	}
}

func (c *ScreenShareClient) SetUser(user *kasugai.User) {
	c.currentUser = user
	log.Printf("Set current user: ID=%s, Name=%s", user.Id.Uuid, user.Name)
}

func (c *ScreenShareClient) SetRoom(roomID *kasugai.Id) {
	c.currentRoom = roomID
	log.Printf("Set current room: ID=%s", roomID.Uuid)
}

func (c *ScreenShareClient) StartScreenShare() error {
	if c.currentUser == nil || c.currentRoom == nil {
		return fmt.Errorf("user or room not set")
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	ctx = metadata.NewOutgoingContext(ctx, metadata.New(map[string]string{
		"user": c.currentUser.Id.Uuid,
	}))

	stream, err := c.mediaService.StartMediaStream(ctx)
	if err != nil {
		return fmt.Errorf("failed to start media stream: %v", err)
	}

	log.Println("Successfully started media stream")

	// Send initial metadata
	initialData := &kasugai.MediaStream{
		Id:       c.currentRoom,
		SenderId: c.currentUser.Id,
		Type:     kasugai.MediaType_SCREEN,
	}
	if err := stream.Send(initialData); err != nil {
		return fmt.Errorf("failed to send initial stream data: %v", err)
	}

	log.Println("Sent initial stream data")

	go c.streamScreenShares(ctx, stream)

	return nil
}

func (c *ScreenShareClient) streamScreenShares(ctx context.Context, stream kasugai.MediaService_StartMediaStreamClient) {
	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()
	buf := new(bytes.Buffer)

	for {
		select {
		case <-ticker.C:
			img, err := screenshare.CaptureDisplay(0)
			if err != nil {
				log.Printf("Error capturing display: %v", err)
				continue
			}

			buf.Reset()
			if err := png.Encode(buf, img); err != nil {
				log.Printf("Error encoding image: %v", err)
				continue
			}

			mediaStream := &kasugai.MediaStream{
				Id:        c.currentRoom,
				SenderId:  c.currentUser.Id,
				Type:      kasugai.MediaType_SCREEN,
				Data:      buf.Bytes(),
				Timestamp: timestamppb.Now(),
			}

			if err := stream.Send(mediaStream); err != nil {
				if err == io.EOF {
					log.Println("Stream closed by server")
					return
				}
				if strings.Contains(err.Error(), "transport is closing") {
					log.Println("Transport is closing, ending stream")
					return
				}
				log.Printf("Error sending screen data: %v", err)
				continue
			}

			log.Printf("Sent screen data: %d bytes", len(buf.Bytes()))

			// Try to receive any messages from the server
			_, err = stream.Recv()
			if err != nil {
				if err == io.EOF {
					log.Println("Server closed the stream")
					return
				}
				if strings.Contains(err.Error(), "transport is closing") {
					log.Println("Transport is closing, ending stream")
					return
				}
				log.Printf("Error receiving from stream: %v", err)
			}

		case <-c.stopShare:
			log.Println("Stopping screen share...")
			return
		case <-ctx.Done():
			log.Println("Context cancelled, ending stream...")
			return
		}
	}
}

func (c *ScreenShareClient) StopScreenShare() error {
	if c.currentUser == nil || c.currentRoom == nil {
		return fmt.Errorf("user or room not set")
	}

	close(c.stopShare)

	ctx := metadata.NewOutgoingContext(context.Background(), metadata.New(map[string]string{
		"user": c.currentUser.Id.Uuid,
	}))

	_, err := c.mediaService.EndMediaStream(ctx, c.currentRoom)
	if err != nil {
		return fmt.Errorf("failed to stop screen share: %v", err)
	}

	log.Println("Successfully stopped screen share")

	return nil
}
