package datastore

import (
	"chat/pkg/kasugai"
	"sync"
)

type DataStore struct {
	mu            sync.RWMutex
	users         map[string]*kasugai.User
	rooms         map[string]*kasugai.Room
	fileTransfers map[string]*kasugai.FileMetadata
	activeStreams map[string]*kasugai.MediaStream
	activeCalls   map[string]*kasugai.VoIPCall
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
			activeStreams: make(map[string]*kasugai.MediaStream),
			activeCalls:   make(map[string]*kasugai.VoIPCall),
		}
	})
	return instance
}

// User operations
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

// Room operations
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
func (ds *DataStore) AddActiveStream(stream *kasugai.MediaStream) {
	ds.mu.Lock()
	defer ds.mu.Unlock()
	ds.activeStreams[stream.Id.Uuid] = stream
}

func (ds *DataStore) GetActiveStream(id string) (*kasugai.MediaStream, bool) {
	ds.mu.RLock()
	defer ds.mu.RUnlock()
	stream, exists := ds.activeStreams[id]
	return stream, exists
}

func (ds *DataStore) RemoveActiveStream(id string) {
	ds.mu.Lock()
	defer ds.mu.Unlock()
	delete(ds.activeStreams, id)
}

// voip
func (ds *DataStore) AddActiveCall(call *kasugai.VoIPCall) {
	ds.mu.Lock()
	defer ds.mu.Unlock()
	ds.activeCalls[call.Id.Uuid] = call
}

func (ds *DataStore) UpdateActiveCall(call *kasugai.VoIPCall) {
	ds.mu.Lock()
	defer ds.mu.Unlock()
	if _, exists := ds.activeCalls[call.Id.Uuid]; exists {
		ds.activeCalls[call.Id.Uuid] = call
	}
}

func (ds *DataStore) RemoveActiveCall(id string) {
	ds.mu.Lock()
	defer ds.mu.Unlock()
	delete(ds.activeCalls, id)
}

func (ds *DataStore) GetActiveCall(id string) (*kasugai.VoIPCall, bool) {
	ds.mu.RLock()
	defer ds.mu.RUnlock()
	call, exists := ds.activeCalls[id]
	return call, exists
}
