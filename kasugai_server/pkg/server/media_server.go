package server

import (
	"bytes"
	"context"
	"fmt"
	"image/png"
	"io"
	"net"
	"os"
	"os/signal"
	"syscall"
	"time"

	"chat/internal/screenshare"
	"chat/pkg/datastore"
	"chat/pkg/kasugai"
	"chat/pkg/stdlog"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/peer"
	"google.golang.org/grpc/reflection"
	"google.golang.org/grpc/status"
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
	kasugai.RegisterMediaServiceServer(s.grpcServer, s.UnimplementedMediaServiceServer)
	reflection.Register(s.grpcServer)

	s.logger.Info(fmt.Sprintf("Media gRPC server started on: %s", address))
	return s.grpcServer.Serve(lis)
}

func (s *MediaServer) Stop() {
	s.logger.Info("Stopping Media server...")
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

func (s *MediaServer) StartMediaStream(id *kasugai.Id, stream kasugai.MediaService_StartMediaStreamServer) error {
	peerInfo, _ := peer.FromContext(stream.Context())
	s.logger.Info(fmt.Sprintf("New media stream connection from: %s", peerInfo.Addr.String()))

	initialData, err := stream.Recv()
	if err != nil {
		s.logger.Error(fmt.Sprintf("Error receiving initial media stream data: %v", err))
		return err
	}

	s.logger.Info(fmt.Sprintf("Media stream started: ID=%s, Type=%s, User=%s",
		initialData.Id.Uuid, initialData.Type, initialData.SenderId.Uuid))

	err = s.dataStore.AddActiveStream(id.Uuid, stream)
	if err != nil {
		return fmt.Errorf("Error adding active stream to datastore: %v", err)
	}

	for {
		mediaData, err := stream.Recv()
		if err == io.EOF {
			s.logger.Info(fmt.Sprintf("Media stream ended: ID=%s", initialData.Id.Uuid))
			s.dataStore.RemoveActiveStream(initialData.Id.Uuid)
			return nil
		}
		if err != nil {
			s.logger.Error(fmt.Sprintf("Error receiving media data: %v", err))
			s.dataStore.RemoveActiveStream(initialData.Id.Uuid)
			return err
		}

		// Process and broadcast the media data
		go s.broadcastMediaData(mediaData)
	}
}

func (s *MediaServer) broadcastMediaData(mediaData *kasugai.MediaStream) {
	room, exists := s.dataStore.GetRoom(mediaData.Id.Uuid)
	if !exists {
		s.logger.Error(fmt.Sprintf("Room not found for stream ID: %s", mediaData.Id.Uuid))
		return
	}

	for _, participantID := range room.ParticipantIds {
		if participantID.Uuid != mediaData.SenderId.Uuid {
			// In a real implementation, you would send this data to the participant's client
			s.logger.Debug(fmt.Sprintf("Sending media data to participant: %s", participantID.Uuid))
		}
	}
}

func (s *MediaServer) sendMediaDataToParticipant(participant *Participant, mediaData *kasugai.MediaStream) error {
	// Implement the logic to send media data to a specific participant
	// This might involve maintaining a separate gRPC stream for each participant
	// or using a different communication method to send the data to clients
	return nil
}

func (s *MediaServer) EndMediaStream(ctx context.Context, req *kasugai.Id) (*kasugai.Ack, error) {
	s.logger.Info(fmt.Sprintf("Request to end media stream: ID=%s", req.Uuid))

	_, exists := s.dataStore.GetActiveStream(req.Uuid)
	if exists != nil {
		s.logger.Warning(fmt.Sprintf("Attempt to end non-existent stream: %s", req.Uuid))
		return &kasugai.Ack{
			Success: false,
			Message: "Stream not found",
		}, status.Error(codes.NotFound, "Stream not found")
	}

	s.dataStore.RemoveActiveStream(req.Uuid)

	s.logger.Info(fmt.Sprintf("Media stream ended: %s", req.Uuid))
	return &kasugai.Ack{
		Success: true,
		Message: "Stream ended successfully",
	}, nil
}

//func (s *MediaServer) ManageVoIPCall(stream kasugai.MediaService_ManageVoIPCallServer) error {
//	s.logger.Info("Managing VoIP call")
//
//	var currentCall *kasugai.VoIPCall
//
//	// Get caller ID from metadata
//	md, ok := metadata.FromIncomingContext(stream.Context())
//	if !ok {
//		return status.Errorf(codes.InvalidArgument, "missing metadata")
//	}
//	callerIDs := md.Get("caller_id")
//	if len(callerIDs) == 0 {
//		return status.Errorf(codes.InvalidArgument, "caller_id not found in metadata")
//	}
//
//	for {
//		signal, err := stream.Recv()
//		if err == io.EOF {
//			s.logger.Info("VoIP call stream ended")
//			return nil
//		}
//		if err != nil {
//			s.logger.Error(fmt.Sprintf("Error receiving VoIP signal: %v", err))
//			return err
//		}
//
//		s.logger.Info(fmt.Sprintf("Received VoIP signal for call %s", signal.CallId.Uuid))
//
//		// Process the VoIP signal
//		//response, err := s.processVoIPSignal(signal, &currentCall)
//		//if err != nil {
//		//	s.logger.Error(fmt.Sprintf("Error processing VoIP signal: %v", err))
//		//	return err
//		//}
//		//
//		//// Send the response back to the client
//		//if err := stream.Send(response); err != nil {
//		//	s.logger.Error(fmt.Sprintf("Error sending VoIP signal: %v", err))
//		//	return err
//		//}
//	}
//}

func (s *MediaServer) handleScreenShare(ctx context.Context, stream kasugai.MediaService_StartMediaStreamServer, initialData *kasugai.MediaStream, room *Room) error {
	s.logger.Info(fmt.Sprintf("Screen sharing started for user: %s", initialData.SenderId.Uuid))

	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()

	buf := new(bytes.Buffer)
	interrupt := make(chan os.Signal, 1)
	signal.Notify(interrupt, os.Interrupt, syscall.SIGTERM)

	for {
		select {
		case <-ticker.C:
			img, err := screenshare.CaptureDisplay(0)
			if err != nil {
				s.logger.Error(fmt.Sprintf("Error capturing display: %v", err))
				return status.Errorf(codes.Internal, "Failed to capture display: %v", err)
			}

			buf.Reset()
			if err := png.Encode(buf, img); err != nil {
				s.logger.Error(fmt.Sprintf("Error encoding image: %v", err))
				return status.Errorf(codes.Internal, "Failed to encode image: %v", err)
			}

			// Broadcast screen data to all participants in the room
			for _, participant := range room.Participants {
				if participant.User.Id.Uuid != initialData.SenderId.Uuid {
					// Send the captured screen through the gRPC stream
					if err := stream.Send(&kasugai.MediaStream{
						Id:        initialData.Id,
						SenderId:  initialData.SenderId,
						Type:      kasugai.MediaType_SCREEN,
						Data:      buf.Bytes(),
						Timestamp: timestamppb.Now(),
					}); err != nil {
						s.logger.Error(fmt.Sprintf("Error sending screen share data: %v", err))
						return err
					}
					s.logger.Debug(fmt.Sprintf("Sent screen update for user: %s, size: %d bytes", initialData.SenderId.Uuid, buf.Len()))
				}
			}

		case <-interrupt:
			s.logger.Info(fmt.Sprintf("Screen sharing interrupted for user: %s", initialData.SenderId.Uuid))
			return status.Error(codes.Canceled, "Screen sharing interrupted")

		case <-ctx.Done():
			s.logger.Info(fmt.Sprintf("Screen sharing stopped for user: %s", initialData.SenderId.Uuid))
			return ctx.Err()
		}
	}
}

func (s *MediaServer) handleAudioStream(ctx context.Context, stream kasugai.MediaService_StartMediaStreamServer, initialData *kasugai.MediaStream, room *Room) error {
	// Implement audio streaming logic here
	// This is a placeholder and should be implemented based on our VoIP requirements
	s.logger.Info(fmt.Sprintf("Audio streaming started for user: %s", initialData.SenderId.Uuid))

	for {
		data, err := stream.Recv()
		if err == io.EOF {
			s.logger.Info(fmt.Sprintf("Audio stream ended for user: %s", initialData.SenderId.Uuid))
			return nil
		}
		if err != nil {
			s.logger.Error(fmt.Sprintf("Error receiving audio data: %v", err))
			return err
		}

		// Process and forward audio data here
		// For example, you might send it to other participants in a call
		s.logger.Debug(fmt.Sprintf("Received audio data from user: %s, size: %d bytes", initialData.SenderId.Uuid, len(data.Data)))

		// Send acknowledgment
		if err := stream.Send(&kasugai.MediaStream{
			Id:        initialData.Id,
			SenderId:  initialData.SenderId,
			Type:      kasugai.MediaType_AUDIO,
			Data:      []byte("ACK"),
			Timestamp: timestamppb.Now(),
		}); err != nil {
			s.logger.Error(fmt.Sprintf("Error sending audio ACK: %v", err))
			return err
		}

		// Check for stream context cancellation
		select {
		case <-ctx.Done():
			s.logger.Info(fmt.Sprintf("Audio streaming stopped for user: %s", initialData.SenderId.Uuid))
			return ctx.Err()
		default:
		}
	}
}
