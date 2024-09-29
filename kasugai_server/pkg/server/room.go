package server

import (
	"chat/pkg/kasugai"
	"errors"
	"sync"
	"time"

	"github.com/google/uuid"
	"google.golang.org/protobuf/types/known/timestamppb"
)

// Update the Room struct to include new fields
type Room struct {
	Channel      *kasugai.Room
	Participants map[string]*Participant
	Broadcast    chan []*RoomContent
	Description  string
	CreatedAt    time.Time
	mu           sync.RWMutex
}

type RoomType int

const (
	DirectRoom RoomType = iota
	GroupRoom
)

// ContentType represents the type of content being sent
type ContentType int

const (
	TextMessage ContentType = iota
	ScreenShare
	FileXfer
)

// RoomContent represents a piece of content (message, screen share, or file) in a room
type RoomContent struct {
	Type        ContentType
	SenderId    string
	RecipientId string // Empty for broadcasts
	Payload     interface{}
	Timestamp   *timestamppb.Timestamp
}

type Participant struct {
	User          *kasugai.User
	Role          ParticipantRole
	DirectChannel chan *RoomContent
}

type ParticipantRole int

const (
	RoleParticipant ParticipantRole = iota
	RoleAdmin
)

type Message struct {
	Text *kasugai.TextMessage
}

type MediaStream struct {
	Media  *kasugai.MediaStream
	Active bool
}

type FileTransfer struct {
	Metadata  *kasugai.FileMetadata
	FileChunk *kasugai.FileChunk
	Status    FileTransferStatus
}

type FileTransferStatus int

const (
	FileTransferPending FileTransferStatus = iota
	FileTransferInProgress
	FileTransferCompleted
	FileTransferFailed
)

// RoomBuilder is used to construct Room objects
type RoomBuilder struct {
	room *Room
}

// NewRoomBuilder creates a new RoomBuilder
func NewRoomBuilder() *RoomBuilder {
	return &RoomBuilder{
		room: &Room{
			Channel: &kasugai.Room{
				Id: &kasugai.Id{Uuid: uuid.New().String()},
			},
			Participants: make(map[string]*Participant, 0),
			Broadcast:    make(chan []*RoomContent, 1024),
			CreatedAt:    time.Now(),
		},
	}
}

// WithName sets the name of the room
func (rb *RoomBuilder) WithName(name string) *RoomBuilder {
	rb.room.Channel.Name = name
	return rb
}

// WithType sets the type of the room
func (rb *RoomBuilder) WithType(roomType RoomType) *RoomBuilder {
	rb.room.Channel.Type = kasugai.RoomType_CHAT
	return rb
}

// WithCreator adds the creator as the first participant and admin
func (rb *RoomBuilder) WithCreator(user *kasugai.User) *RoomBuilder {
	rb.room.Channel.CreatorId = user.Id
	return rb
}

// WithParticipant adds a participant to the room
func (rb *RoomBuilder) WithParticipant(user *kasugai.User) *RoomBuilder {
	if _, exists := rb.room.Participants[user.Id.Uuid]; !exists {
		rb.room.Participants[user.Id.Uuid] = &Participant{
			User: user,
			Role: RoleParticipant,
		}

		rb.room.Channel.ParticipantIds = append(rb.room.Channel.ParticipantIds, user.Id)
	}
	return rb
}

// WithDescription sets the description of the room
func (rb *RoomBuilder) WithDescription(description string) *RoomBuilder {
	rb.room.Description = description
	return rb
}

// Build constructs and returns the Room object
func (rb *RoomBuilder) Build() (*Room, error) {
	if rb.room.Channel.Name == "" {
		return nil, errors.New("room must have a name")
	}
	// if len(rb.room.Participants) == 0 {
	// 	return nil, errors.New("room must have at least one participant")
	// }
	// if rb.room.Type == DirectRoom && len(rb.room.Participants) > 2 {
	// 	return nil, errors.New("direct room cannot have more than two participants")
	// }

	return rb.room, nil
}
