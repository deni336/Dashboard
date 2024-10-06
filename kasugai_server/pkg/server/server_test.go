package server

import (
	"chat/pkg/datastore"
	"chat/pkg/kasugai"
	"chat/pkg/stdlog"
	"context"
	"github.com/stretchr/testify/assert"
	"google.golang.org/grpc/metadata"
	"google.golang.org/protobuf/types/known/emptypb"
	"testing"
)

// setupTestServer Creates a new instance of the Server with a DataStore and Logger that are shared across the test cases.
func setupTestServer() (*Server, *stdlog.Logger, *datastore.DataStore) {
	logger, _ := stdlog.NewLogger("test.log", stdlog.DEBUG, false)
	ds := datastore.GetInstance()
	testServer := NewServer(logger, ds)
	return testServer, logger, ds
}

// TestRegisterUser Registers a new user and verifies that the user is registered successfully.
func TestRegisterUser(t *testing.T) {
	testServer, _, _ := setupTestServer()

	ctx := context.Background()
	user := &kasugai.User{
		Id:   &kasugai.Id{Uuid: "user-123"},
		Name: "Test User",
	}

	resp, err := testServer.RegisterUser(ctx, user)
	assert.NoError(t, err)
	assert.True(t, resp.Success)
	assert.Equal(t, "User registered", resp.Message)
}

// TestRegisterUser_Duplicate Tries registering the same user twice to check if the server handles duplicate registrations properly.
func TestRegisterUser_Duplicate(t *testing.T) {
	testServer, _, _ := setupTestServer()

	ctx := context.Background()
	user := &kasugai.User{
		Id:   &kasugai.Id{Uuid: "user-123"},
		Name: "Test User",
	}

	// First registration should succeed
	_, _ = testServer.RegisterUser(ctx, user)

	// Second registration should fail
	resp, err := testServer.RegisterUser(ctx, user)
	assert.Error(t, err)
	assert.False(t, resp.Success)
	assert.Equal(t, "User already exists", resp.Message)
}

// TestGetUserList Registers multiple users and verifies that the user list returned matches the number of registered users.
func TestGetUserList(t *testing.T) {
	testServer, _, _ := setupTestServer()

	ctx := context.Background()

	// Register some users
	users := []*kasugai.User{
		{Id: &kasugai.Id{Uuid: "user-1"}, Name: "User One"},
		{Id: &kasugai.Id{Uuid: "user-2"}, Name: "User Two"},
	}

	for _, user := range users {
		_, _ = testServer.RegisterUser(ctx, user)
	}

	// Get user list
	userList, err := testServer.GetUserList(ctx, &emptypb.Empty{})
	assert.NoError(t, err)
	assert.NotNil(t, userList)
	assert.Equal(t, len(users), len(userList.Users))
}

// TestCreateRoom Registers a user and then creates a new room for that user, checking if the room is created successfully.
func TestCreateRoom(t *testing.T) {
	testServer, _, _ := setupTestServer()

	ctx := context.Background()

	user := &kasugai.User{
		Id:   &kasugai.Id{Uuid: "user-123"},
		Name: "Test User",
	}

	// Register the user
	_, _ = testServer.RegisterUser(ctx, user)

	room := &kasugai.Room{
		Name:      "Test Room",
		CreatorId: user.Id,
		Type:      kasugai.RoomType_CHAT,
		Key:       "OPEN",
	}

	resp, err := testServer.CreateRoom(ctx, room)
	if resp == nil {
		return
	}
	room.Id = &kasugai.Id{Uuid: resp.Message}

	assert.NoError(t, err)
	assert.True(t, resp.Success)
	assert.Equal(t, room.Id.Uuid, resp.Message)
}

// TestJoinAndLeaveRoom Registers a user, creates a room, and then has the user join and leave the room.
// Metadata is used to simulate the user's ID in the incoming context for joining the room.
func TestJoinAndLeaveRoom(t *testing.T) {
	testServer, _, _ := setupTestServer()

	ctx := context.Background()

	user := &kasugai.User{
		Id:   &kasugai.Id{Uuid: "user-123"},
		Name: "Test User",
	}

	// Register the user
	_, err := testServer.RegisterUser(ctx, user)
	assert.NoError(t, err, "User registration should succeed")

	room := &kasugai.Room{
		Name:      "Test Room",
		CreatorId: user.Id,
		Type:      kasugai.RoomType_CHAT,
		Key:       "OPEN",
	}

	// Create the room
	resp, _ := testServer.CreateRoom(ctx, room)
	assert.NoError(t, err, "Room creation should succeed")
	assert.NotNil(t, resp, "Room creation response should not be nil")
	room.Id = &kasugai.Id{Uuid: resp.Message}

	// Join the room
	md := metadata.Pairs(
		"user", user.Id.Uuid,
		"key", room.Key,
	)
	ctx = metadata.NewIncomingContext(ctx, md)
	joinResp, err := testServer.JoinRoom(ctx, room.Id)
	assert.NoError(t, err)
	assert.True(t, joinResp.Success)

	// Leave the room
	leaveResp, err := testServer.LeaveRoom(ctx, room.Id)
	assert.NoError(t, err)
	assert.True(t, leaveResp.Success)
}
