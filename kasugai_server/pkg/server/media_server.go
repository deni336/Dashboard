package server

import (
	"context"
	"fmt"
	"io"
	"net"
	"time"

	"chat/pkg/datastore"
	"chat/pkg/kasugai"
	"chat/pkg/stdlog"

	"google.golang.org/grpc"
	"google.golang.org/grpc/peer"
	"google.golang.org/grpc/reflection"
	"google.golang.org/protobuf/types/known/timestamppb"
)

type MediaServer struct {
	kasugai.UnimplementedMediaServiceServer
	dataStore  *datastore.DataStore
	grpcServer *grpc.Server
	logger     *stdlog.Logger
}

func NewMediaServer(logger *stdlog.Logger, ds *datastore.DataStore) *MediaServer {
	return &MediaServer{
		dataStore: ds,
		logger:    logger,
	}
}

func (s *MediaServer) Start(address string) error {
	lis, err := net.Listen("tcp", address)
	if err != nil {
		return fmt.Errorf("failed to listen: %v", err)
	}

	s.grpcServer = grpc.NewServer()
	kasugai.RegisterMediaServiceServer(s.grpcServer, s)
	reflection.Register(s.grpcServer)

	s.logger.Info(fmt.Sprintf("Media gRPC server started on: %s", address))
	return s.grpcServer.Serve(lis)
}

func (s *MediaServer) Stop() {
	s.logger.Info("Stopping Media server...")
	if s.grpcServer == nil {
		s.logger.Warning("Media server was not started")
		return
	}
	stopped := make(chan struct{})
	go func() {
		s.grpcServer.GracefulStop()
		close(stopped)
	}()

	t := time.NewTimer(10 * time.Second)
	select {
	case <-stopped:
		s.logger.Info("Media server stopped gracefully")
	case <-t.C:
		s.logger.Warning("Media server stop timeout, forcing shutdown")
		s.grpcServer.Stop()
	}
	t.Stop()
}

// StartMediaStream is a single bidirectional stream per connected user, used
// for both roles at once: relaying this user's own captured frames (when
// they're screen-sharing) to the rest of the room, and delivering other
// participants' frames back to this user (when they're just watching). The
// first message on the stream is a pure registration message (empty Data)
// identifying the room and user; every message after that is relayed to the
// rest of the room, including empty-Data messages, which double as an
// explicit "I stopped sharing" signal.
func (s *MediaServer) StartMediaStream(stream kasugai.MediaService_StartMediaStreamServer) error {
	peerInfo, _ := peer.FromContext(stream.Context())
	peerAddress := "unknown"
	if peerInfo != nil && peerInfo.Addr != nil {
		peerAddress = peerInfo.Addr.String()
	}
	s.logger.Info(fmt.Sprintf("New media stream connection from: %s", peerAddress))

	initialData, err := stream.Recv()
	if err != nil {
		s.logger.Error(fmt.Sprintf("Error receiving initial media stream data: %v", err))
		return err
	}
	if initialData.Id == nil || initialData.Id.Uuid == "" || initialData.SenderId == nil || initialData.SenderId.Uuid == "" {
		return fmt.Errorf("invalid media stream registration")
	}

	roomId := initialData.Id.Uuid
	senderId := initialData.SenderId.Uuid
	s.logger.Info(fmt.Sprintf("Media channel registered: room=%s, user=%s", roomId, senderId))

	streamVersion := s.dataStore.AddActiveStream(senderId, stream)
	defer func() {
		s.dataStore.RemoveActiveStream(senderId, streamVersion)
		// Safety net for ungraceful disconnects (crash, closed tab) that never
		// sent an explicit stop frame -- let viewers know to clear their display.
		s.broadcastToRoom(roomId, &kasugai.MediaStream{
			Id:        &kasugai.Id{Uuid: roomId},
			SenderId:  &kasugai.Id{Uuid: senderId},
			Type:      kasugai.MediaType_SCREEN,
			Data:      []byte{},
			Timestamp: timestamppb.Now(),
		})
	}()

	for {
		mediaData, err := stream.Recv()
		if err == io.EOF {
			s.logger.Info(fmt.Sprintf("Media stream ended: user=%s", senderId))
			return nil
		}
		if err != nil {
			s.logger.Error(fmt.Sprintf("Error receiving media data: %v", err))
			return err
		}

		s.broadcastToRoom(roomId, mediaData)
	}
}

// broadcastToRoom delivers mediaData to every other participant in the room
// who currently has a registered media stream (i.e. is on the screen-share
// page). Participants without one (not currently watching) are skipped.
func (s *MediaServer) broadcastToRoom(roomId string, mediaData *kasugai.MediaStream) {
	participants, exists := s.dataStore.GetRoomParticipants(&kasugai.Id{Uuid: roomId})
	if !exists {
		s.logger.Error(fmt.Sprintf("Room not found for media broadcast: %s", roomId))
		return
	}

	for _, user := range participants.Participants {
		if user.Id.Uuid == mediaData.SenderId.Uuid {
			continue // don't echo back to the sender
		}
		viewerStream, err := s.dataStore.GetActiveStream(user.Id.Uuid)
		if err != nil {
			continue // not currently watching
		}
		if err := viewerStream.Send(mediaData); err != nil {
			s.logger.Error(fmt.Sprintf("Error sending media frame to %s: %v", user.Id.Uuid, err))
		}
	}
}

// EndMediaStream is an optional explicit signal; the real stop mechanism is
// sending an empty-Data frame (or disconnecting) on the still-open
// StartMediaStream channel, both of which broadcastToRoom already handles.
func (s *MediaServer) EndMediaStream(ctx context.Context, req *kasugai.Id) (*kasugai.Ack, error) {
	s.logger.Info(fmt.Sprintf("Received explicit end-stream notice for: %s", req.Uuid))
	return &kasugai.Ack{Success: true, Message: "Acknowledged"}, nil
}
