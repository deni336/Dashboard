package datastore

import (
	"chat/pkg/kasugai"
	"fmt"
	"sync"
)

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

// User operations TODO: add deletes
func (ds *DataStore) AddUser(user *kasugai.User) {
	ds.mu.Lock()
	defer ds.mu.Unlock()
	ds.users[user.Id.Uuid] = user
}

func (ds *DataStore) GetUser(id string) (*kasugai.User, bool) {
	ds.mu.RLock()
	defer ds.mu.RUnlock()
	user, exists := ds.users[id]
	return user, exists
}

// Room operations TODO: add deletes
func (ds *DataStore) AddRoom(room *kasugai.Room) {
	ds.mu.Lock()
	defer ds.mu.Unlock()
	ds.rooms[room.Id.Uuid] = room
}

func (ds *DataStore) GetRoom(id string) (*kasugai.Room, bool) {
	ds.mu.RLock()
	defer ds.mu.RUnlock()
	room, exists := ds.rooms[id]
	return room, exists
}

// File transfer operations
func (ds *DataStore) AddFileTransfer(fileTransfer *kasugai.FileMetadata) {
	ds.mu.Lock()
	defer ds.mu.Unlock()
	ds.fileTransfers[fileTransfer.Id.Uuid] = fileTransfer
}

func (ds *DataStore) GetFileTransfer(id string) (*kasugai.FileMetadata, bool) {
	ds.mu.RLock()
	defer ds.mu.RUnlock()
	fileTransfer, exists := ds.fileTransfers[id]
	return fileTransfer, exists
}

// Media stream operations
func (ds *DataStore) AddActiveStream(senderId string, stream kasugai.MediaService_StartMediaStreamServer) error {
	ds.mu.Lock()
	defer ds.mu.Unlock()
	if _, exists := ds.activeStreams[senderId]; exists {
		return fmt.Errorf("Media stream connection already exists for sender ID: %s", senderId)
	}
	ds.activeStreams[senderId] = stream
	return nil
}

func (ds *DataStore) GetActiveStream(id string) (kasugai.MediaService_StartMediaStreamServer, error) {
	ds.mu.RLock()
	defer ds.mu.RUnlock()
	stream, exist := ds.activeStreams[id]
	if !exist {
		return nil, fmt.Errorf("Media stream connection already exists for sender ID: %s", id)
	}
	return stream, nil
}

func (ds *DataStore) RemoveActiveStream(id string) {
	ds.mu.Lock()
	defer ds.mu.Unlock()
	delete(ds.activeStreams, id)
}

// voip
func (ds *DataStore) AddActiveCall(id string, stream kasugai.MediaService_ManageVoIPCallServer) error {
	ds.mu.Lock()
	defer ds.mu.Unlock()

	if _, exists := ds.activeCalls[id]; exists {
		return fmt.Errorf("VoIP stream connection already exists for call ID: %s", id)
	}
	ds.activeCalls[id] = stream
	return nil
}

func (ds *DataStore) RemoveActiveCall(id string) {
	ds.mu.Lock()
	defer ds.mu.Unlock()
	delete(ds.activeCalls, id)
}

func (ds *DataStore) GetActiveCall(id string) (kasugai.MediaService_ManageVoIPCallServer, error) {
	ds.mu.RLock()
	defer ds.mu.RUnlock()
	call, exists := ds.activeCalls[id]
	if !exists {
		return nil, fmt.Errorf("VoIP stream connection doesn't exists for call ID: %s", id)
	}
	return call, nil
}
