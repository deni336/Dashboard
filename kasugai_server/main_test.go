package main

import (
	"context"
	"os"
	"os/exec"
	"testing"
	"time"

	"chat/pkg/kasugai"
	"google.golang.org/grpc"
)

func TestMainApp(t *testing.T) {
	// Start the application as a subprocess
	cmd := exec.Command("go", "run", "main.go")
	cmd.Env = append(os.Environ(), "CONFIG_PATH=config.json")

	if err := cmd.Start(); err != nil {
		t.Fatalf("Failed to start main app: %v", err)
	}

	// Give the application time to start up
	time.Sleep(5 * time.Second)

	// Connect to the gRPC server
	conn, err := grpc.Dial("localhost:8008", grpc.WithInsecure())
	if err != nil {
		t.Fatalf("Failed to connect to gRPC server: %v", err)
	}
	defer conn.Close()

	client := kasugai.NewUserServiceClient(conn)

	// Register a user
	ctx, cancel := context.WithTimeout(context.Background(), time.Second*5)
	defer cancel()

	_, err = client.RegisterUser(ctx, &kasugai.User{Id: &kasugai.Id{Uuid: "test-user-1"}, Name: "Test User"})
	if err != nil {
		t.Errorf("Failed to register user: %v", err)
	}

	// Shut down the application gracefully
	if err := cmd.Process.Signal(os.Interrupt); err != nil {
		t.Fatalf("Failed to shut down main app: %v", err)
	}

	if _, err := cmd.Process.Wait(); err != nil {
		t.Fatalf("Failed to wait for app shutdown: %v", err)
	}
}
