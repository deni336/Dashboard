package datastore

import (
	"chat/pkg/kasugai"
	"fmt"
	"sync"
)

// DataStore active datastore object
type DataStore struct {
	mu            sync.RWMutex
	users         map[string]*kasugai.User
	rooms         map[string]*kasugai.Room
	fileTransfers map[string]*kasugai.FileMetadata
	activeStreams map[string]kasugai.MediaService_StartMediaStreamServer
	activeCalls   map[string]kasugai.MediaService_ManageVoIPCallServer
}

var (
	instance *DataStore
	once     sync.Once
)

// GetInstance get datastore instance
func GetInstance() *DataStore {
	once.Do(func() {
		instance = &DataStore{
			users:         make(map[string]*kasugai.User),
			rooms:         make(map[string]*kasugai.Room),
			fileTransfers: make(map[string]*kasugai.FileMetadata),
			activeStreams: make(map[string]kasugai.MediaService_StartMediaStreamServer),
			activeCalls:   make(map[string]kasugai.MediaService_ManageVoIPCallServer),
		}
	})
	return instance
}

// AddUser User operations
func (ds *DataStore) AddUser(user *kasugai.User) {
	ds.mu.Lock()
	defer ds.mu.Unlock()
	ds.users[user.Id.Uuid] = user
}

// GetUser get a user
func (ds *DataStore) GetUser(id string) (*kasugai.User, bool) {
	ds.mu.RLock()
	defer ds.mu.RUnlock()
	user, exists := ds.users[id]
	return user, exists
}

// GetUserList retrieve list of users
func (ds *DataStore) GetUserList() (*kasugai.UserList, bool) {
	ds.mu.RLock()
	defer ds.mu.RUnlock()

	userList := &kasugai.UserList{Users: []*kasugai.User{}}
	for _, user := range ds.users {
		userList.Users = append(userList.Users, user)
	}

	if len(userList.Users) == 0 {
		return userList, false
	}

	return userList, true
}

// RemoveUser removes a user from the datastore
func (ds *DataStore) RemoveUser(user *kasugai.User) bool {
	ds.mu.RLock()
	defer ds.mu.RUnlock()

	user, exists := ds.users[user.Id.Uuid]
	if !exists {
		return false
	}

	delete(ds.users, user.Id.Uuid)
	return true
}

// AddRoom Room operations
func (ds *DataStore) AddRoom(room *kasugai.Room) {
	ds.mu.Lock()
	defer ds.mu.Unlock()
	ds.rooms[room.Id.Uuid] = room
}

// GetRoom get a room by id
func (ds *DataStore) GetRoom(id string) (*kasugai.Room, bool) {
	ds.mu.RLock()
	defer ds.mu.RUnlock()
	room, exists := ds.rooms[id]
	return room, exists
}

// GetRoomList retrieve list of rooms from the server
func (ds *DataStore) GetRoomList() (*kasugai.RoomList, bool) {
	ds.mu.RLock()
	defer ds.mu.RUnlock()

	roomList := &kasugai.RoomList{}
	for _, room := range ds.rooms {
		roomList.Rooms = append(roomList.Rooms, room)
	}
	if len(roomList.Rooms) == 0 {
		return roomList, false
	}
	return roomList, true
}

// RemoveRoom delete room from datastore
func (ds *DataStore) RemoveRoom(room *kasugai.Room) bool {
	ds.mu.Lock()
	defer ds.mu.Unlock()

	room, exists := ds.rooms[room.Id.Uuid]
	if !exists {
		return false
	}
	delete(ds.rooms, room.Id.Uuid)
	return true
}

// AddRoomParticipants adds a user to the room participant list of the datastore
func (ds *DataStore) AddRoomParticipants(user *kasugai.User, roomId *kasugai.Id) (*kasugai.RoomParticipants, bool) {
	ds.mu.Lock()

	room, exists := ds.rooms[roomId.Uuid]
	if !exists {
		ds.mu.Unlock()
		return nil, false
	}

	// Add user to room participants
	room.ParticipantIds = append(room.ParticipantIds, user.Id)
	participantIds := make([]*kasugai.Id, len(room.ParticipantIds))
	copy(participantIds, room.ParticipantIds)

	ds.mu.Unlock()

	participants := &kasugai.RoomParticipants{RoomId: roomId}
	for _, usrId := range participantIds {
		u, exists := ds.GetUser(usrId.Uuid)
		if exists {
			participants.Participants = append(participants.Participants, u)
		}
	}

	return participants, true
}

// GetRoomParticipants gets the list of participants in the datastore room
func (ds *DataStore) GetRoomParticipants(id *kasugai.Id) (*kasugai.RoomParticipants, bool) {
	ds.mu.Lock()

	room, exists := ds.rooms[id.Uuid]
	if !exists {
		ds.mu.Unlock()
		return nil, false
	}

	participantIds := make([]*kasugai.Id, len(room.ParticipantIds))
	copy(participantIds, room.ParticipantIds)

	ds.mu.RUnlock()

	participants := &kasugai.RoomParticipants{RoomId: id}
	for _, usrId := range participantIds {
		u, exists := ds.GetUser(usrId.Uuid)
		if exists {
			participants.Participants = append(participants.Participants, u)
		}
	}

	return participants, true
}

// RemoveParticipant remove user from room
func (ds *DataStore) RemoveParticipant(id *kasugai.Id, user *kasugai.User) bool {
	ds.mu.Lock()
	defer ds.mu.Unlock()

	room, exists := ds.rooms[id.Uuid]
	if !exists {
		return false
	}

	for i, participantId := range room.ParticipantIds {
		if participantId.Uuid == user.Id.Uuid {
			// Remove the user by appending all elements except the one at index i
			room.ParticipantIds = append(room.ParticipantIds[:i], room.ParticipantIds[i+1:]...)
			return true
		}
	}

	return false
}

/*  FILE TRANSFER  */

// AddFileTransfer File transfer operations
func (ds *DataStore) AddFileTransfer(fileTransfer *kasugai.FileMetadata) {
	ds.mu.Lock()
	defer ds.mu.Unlock()
	ds.fileTransfers[fileTransfer.Id.Uuid] = fileTransfer
}

// GetFileTransfer get a file transfer node
func (ds *DataStore) GetFileTransfer(id string) (*kasugai.FileMetadata, bool) {
	ds.mu.RLock()
	defer ds.mu.RUnlock()
	fileTransfer, exists := ds.fileTransfers[id]
	return fileTransfer, exists
}

// AddActiveStream stream operations
func (ds *DataStore) AddActiveStream(senderId string, stream kasugai.MediaService_StartMediaStreamServer) error {
	ds.mu.Lock()
	defer ds.mu.Unlock()
	if _, exists := ds.activeStreams[senderId]; exists {
		return fmt.Errorf("media stream connection already exists for sender ID: %s", senderId)
	}
	ds.activeStreams[senderId] = stream
	return nil
}

// GetActiveStream get an active stream
func (ds *DataStore) GetActiveStream(id string) (kasugai.MediaService_StartMediaStreamServer, error) {
	ds.mu.RLock()
	defer ds.mu.RUnlock()
	stream, exist := ds.activeStreams[id]
	if !exist {
		return nil, fmt.Errorf("media stream connection already exists for sender ID: %s", id)
	}
	return stream, nil
}

// RemoveActiveStream remove active stream
func (ds *DataStore) RemoveActiveStream(id string) {
	ds.mu.Lock()
	defer ds.mu.Unlock()
	delete(ds.activeStreams, id)
}

// AddActiveCall add a call stream
func (ds *DataStore) AddActiveCall(id string, stream kasugai.MediaService_ManageVoIPCallServer) error {
	ds.mu.Lock()
	defer ds.mu.Unlock()

	if _, exists := ds.activeCalls[id]; exists {
		return fmt.Errorf("VoIP stream connection already exists for call ID: %s", id)
	}
	ds.activeCalls[id] = stream
	return nil
}

// RemoveActiveCall remove active call
func (ds *DataStore) RemoveActiveCall(id string) {
	ds.mu.Lock()
	defer ds.mu.Unlock()
	delete(ds.activeCalls, id)
}

// GetActiveCall get active calls
func (ds *DataStore) GetActiveCall(id string) (kasugai.MediaService_ManageVoIPCallServer, error) {
	ds.mu.RLock()
	defer ds.mu.RUnlock()
	call, exists := ds.activeCalls[id]
	if !exists {
		return nil, fmt.Errorf("VoIP stream connection doesn't exists for call ID: %s", id)
	}
	return call, nil
}
