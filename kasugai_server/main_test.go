//package main
//
//import (
//	"context"
//	"os"
//	"os/exec"
//	"testing"
//	"time"
//
//	"chat/pkg/kasugai"
//	"google.golang.org/grpc"
//)
//
//func TestMainApp(t *testing.T) {
//	// Start the application as a subprocess
//	cmd := exec.Command("go", "run", "main.go")
//	cmd.Env = append(os.Environ(), "CONFIG_PATH=config.json")
//
//	if err := cmd.Start(); err != nil {
//		t.Fatalf("Failed to start main app: %v", err)
//	}
//
//	// Give the application time to start up
//	time.Sleep(5 * time.Second)
//
//	// Connect to the gRPC server
//	conn, err := grpc.Dial("localhost:8008", grpc.WithInsecure())
//	if err != nil {
//		t.Fatalf("Failed to connect to gRPC server: %v", err)
//	}
//	defer conn.Close()
//
//	client := kasugai.NewUserServiceClient(conn)
//
//	// Register a user
//	ctx, cancel := context.WithTimeout(context.Background(), time.Second*5)
//	defer cancel()
//
//	_, err = client.RegisterUser(ctx, &kasugai.User{Id: &kasugai.Id{Uuid: "test-user-1"}, Name: "Test User"})
//	if err != nil {
//		t.Errorf("Failed to register user: %v", err)
//	}
//
//	// Shut down the application gracefully
//	if err := cmd.Process.Signal(os.Interrupt); err != nil {
//		t.Fatalf("Failed to shut down main app: %v", err)
//	}
//
//	if _, err := cmd.Process.Wait(); err != nil {
//		t.Fatalf("Failed to wait for app shutdown: %v", err)
//	}
//}

package main

import (
	"chat/internal/messagegen"
	"log"
	"os"
	"os/exec"
	"testing"
	"time"

	"chat/internal/clients"
	"chat/pkg/kasugai"
	"github.com/stretchr/testify/assert"
)

const (
	chatServerAddress = "localhost:8008"
	messageInterval   = 2 * time.Second // Interval between each generated message
)

func TestChatClientIntegration(t *testing.T) {
	//Start the application as a subprocess
	cmd := exec.Command("go", "run", "main.go")
	cmd.Env = append(os.Environ(), "CONFIG_PATH=config.json")

	if err := cmd.Start(); err != nil {
		t.Fatalf("Failed to start main app: %v", err)
	}

	// Give the application time to start up
	time.Sleep(5 * time.Second)

	// 1. Setup client
	client, err := clients.NewKasugaiClient(chatServerAddress)
	assert.NoError(t, err, "Failed to create chat client")
	defer client.Close()

	username := "TestUserIntegration"
	// 2. Register User
	err = registerUser(client, username)
	assert.NoError(t, err, "Failed to register user")

	roomName := "IntegrationTestRoom"
	// 3. Create and Join Room
	roomId, err := createAndJoinRoom(client, roomName)
	assert.NoError(t, err, "Failed to create and join room")

	// 4. Start Receiving Messages
	startReceivingMessages(client)

	// 5. Generate and Send Fake Messages
	sendMessagesAndValidate(client, roomId, t)

	// 6. Leave Room
	err = client.LeaveRoom()
	assert.NoError(t, err, "Failed to leave room")
}

// 2. Register User
func registerUser(client *clients.KasugaiClient, username string) error {
	err := client.RegisterUser(username)
	if err == nil {
		log.Printf("User '%s' registered successfully", username)
	}
	return err
}

// 3. Create & Join Room
func createAndJoinRoom(client *clients.KasugaiClient, key string) (*kasugai.Id, error) {
	room := &kasugai.Room{
		Name:      "TestRoom",
		Type:      kasugai.RoomType_CHAT,
		CreatorId: client.CurrentUser.Id,
	}

	roomId, err := client.CreateRoom(room, key)
	if err != nil {
		return nil, err
	}
	log.Printf("Room '%s' created successfully", room.Name)

	err = client.JoinRoom(roomId)
	if err != nil {
		return nil, err
	}
	log.Printf("Joined room '%s' successfully", room.Name)

	return roomId, nil
}

// 4. Start Receiving Messages
func startReceivingMessages(client *clients.KasugaiClient) {
	go func() {
		err := client.ReceiveTextMessages()
		if err != nil {
			log.Printf("Error receiving messages: %v", err)
		}
	}()
}

// 5. Generate Fake Messages and Validate
func sendMessagesAndValidate(client *clients.KasugaiClient, roomId *kasugai.Id, t *testing.T) {
	messageGenerator := messagegen.NewMessageGenerator(messageInterval)

	// Start generating messages for testing
	messageGenerator.Start(func(message string) {
		// Send message and validate
		err := client.SendTextMessage(message)
		assert.NoError(t, err, "Error sending message")
		if err == nil {
			log.Printf("Message sent: '%s'", message)
		} else {
			t.Errorf("Failed to send message: %s", message)
		}
	})

	// Run the message generator for a short duration to validate sending messages
	time.Sleep(5 * messageInterval)
	messageGenerator.Stop()
}
