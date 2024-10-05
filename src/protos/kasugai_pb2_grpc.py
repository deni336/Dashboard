# Generated by the gRPC Python protocol compiler plugin. DO NOT EDIT!
"""Client and server classes corresponding to protobuf-defined services."""
import grpc
import warnings

from google.protobuf import empty_pb2 as google_dot_protobuf_dot_empty__pb2
import protos.kasugai_pb2 as kasugai__pb2

GRPC_GENERATED_VERSION = '1.66.1'
GRPC_VERSION = grpc.__version__
_version_not_supported = False

try:
    from grpc._utilities import first_version_is_lower
    _version_not_supported = first_version_is_lower(GRPC_VERSION, GRPC_GENERATED_VERSION)
except ImportError:
    _version_not_supported = True

if _version_not_supported:
    raise RuntimeError(
        f'The grpc package installed is at version {GRPC_VERSION},'
        + f' but the generated code in kasugai_pb2_grpc.py depends on'
        + f' grpcio>={GRPC_GENERATED_VERSION}.'
        + f' Please upgrade your grpc module to grpcio>={GRPC_GENERATED_VERSION}'
        + f' or downgrade your generated code using grpcio-tools<={GRPC_VERSION}.'
    )


class UserServiceStub(object):
    """Service definitions
    """

    def __init__(self, channel):
        """Constructor.

        Args:
            channel: A grpc.Channel.
        """
        self.RegisterUser = channel.unary_unary(
                '/kasugai.UserService/RegisterUser',
                request_serializer=kasugai__pb2.User.SerializeToString,
                response_deserializer=kasugai__pb2.Ack.FromString,
                _registered_method=True)
        self.UpdateUserStatus = channel.unary_unary(
                '/kasugai.UserService/UpdateUserStatus',
                request_serializer=kasugai__pb2.User.SerializeToString,
                response_deserializer=kasugai__pb2.Ack.FromString,
                _registered_method=True)
        self.GetUserList = channel.unary_unary(
                '/kasugai.UserService/GetUserList',
                request_serializer=google_dot_protobuf_dot_empty__pb2.Empty.SerializeToString,
                response_deserializer=kasugai__pb2.UserList.FromString,
                _registered_method=True)
        self.GetUserById = channel.unary_unary(
                '/kasugai.UserService/GetUserById',
                request_serializer=kasugai__pb2.Id.SerializeToString,
                response_deserializer=kasugai__pb2.User.FromString,
                _registered_method=True)


class UserServiceServicer(object):
    """Service definitions
    """

    def RegisterUser(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')

    def UpdateUserStatus(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')

    def GetUserList(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')

    def GetUserById(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')


def add_UserServiceServicer_to_server(servicer, server):
    rpc_method_handlers = {
            'RegisterUser': grpc.unary_unary_rpc_method_handler(
                    servicer.RegisterUser,
                    request_deserializer=kasugai__pb2.User.FromString,
                    response_serializer=kasugai__pb2.Ack.SerializeToString,
            ),
            'UpdateUserStatus': grpc.unary_unary_rpc_method_handler(
                    servicer.UpdateUserStatus,
                    request_deserializer=kasugai__pb2.User.FromString,
                    response_serializer=kasugai__pb2.Ack.SerializeToString,
            ),
            'GetUserList': grpc.unary_unary_rpc_method_handler(
                    servicer.GetUserList,
                    request_deserializer=google_dot_protobuf_dot_empty__pb2.Empty.FromString,
                    response_serializer=kasugai__pb2.UserList.SerializeToString,
            ),
            'GetUserById': grpc.unary_unary_rpc_method_handler(
                    servicer.GetUserById,
                    request_deserializer=kasugai__pb2.Id.FromString,
                    response_serializer=kasugai__pb2.User.SerializeToString,
            ),
    }
    generic_handler = grpc.method_handlers_generic_handler(
            'kasugai.UserService', rpc_method_handlers)
    server.add_generic_rpc_handlers((generic_handler,))
    server.add_registered_method_handlers('kasugai.UserService', rpc_method_handlers)


 # This class is part of an EXPERIMENTAL API.
class UserService(object):
    """Service definitions
    """

    @staticmethod
    def RegisterUser(request,
            target,
            options=(),
            channel_credentials=None,
            call_credentials=None,
            insecure=False,
            compression=None,
            wait_for_ready=None,
            timeout=None,
            metadata=None):
        return grpc.experimental.unary_unary(
            request,
            target,
            '/kasugai.UserService/RegisterUser',
            kasugai__pb2.User.SerializeToString,
            kasugai__pb2.Ack.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True)

    @staticmethod
    def UpdateUserStatus(request,
            target,
            options=(),
            channel_credentials=None,
            call_credentials=None,
            insecure=False,
            compression=None,
            wait_for_ready=None,
            timeout=None,
            metadata=None):
        return grpc.experimental.unary_unary(
            request,
            target,
            '/kasugai.UserService/UpdateUserStatus',
            kasugai__pb2.User.SerializeToString,
            kasugai__pb2.Ack.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True)

    @staticmethod
    def GetUserList(request,
            target,
            options=(),
            channel_credentials=None,
            call_credentials=None,
            insecure=False,
            compression=None,
            wait_for_ready=None,
            timeout=None,
            metadata=None):
        return grpc.experimental.unary_unary(
            request,
            target,
            '/kasugai.UserService/GetUserList',
            google_dot_protobuf_dot_empty__pb2.Empty.SerializeToString,
            kasugai__pb2.UserList.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True)

    @staticmethod
    def GetUserById(request,
            target,
            options=(),
            channel_credentials=None,
            call_credentials=None,
            insecure=False,
            compression=None,
            wait_for_ready=None,
            timeout=None,
            metadata=None):
        return grpc.experimental.unary_unary(
            request,
            target,
            '/kasugai.UserService/GetUserById',
            kasugai__pb2.Id.SerializeToString,
            kasugai__pb2.User.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True)


class RoomServiceStub(object):
    """Missing associated documentation comment in .proto file."""

    def __init__(self, channel):
        """Constructor.

        Args:
            channel: A grpc.Channel.
        """
        self.CreateRoom = channel.unary_unary(
                '/kasugai.RoomService/CreateRoom',
                request_serializer=kasugai__pb2.Room.SerializeToString,
                response_deserializer=kasugai__pb2.Ack.FromString,
                _registered_method=True)
        self.JoinRoom = channel.unary_unary(
                '/kasugai.RoomService/JoinRoom',
                request_serializer=kasugai__pb2.Id.SerializeToString,
                response_deserializer=kasugai__pb2.Ack.FromString,
                _registered_method=True)
        self.LeaveRoom = channel.unary_unary(
                '/kasugai.RoomService/LeaveRoom',
                request_serializer=kasugai__pb2.Id.SerializeToString,
                response_deserializer=kasugai__pb2.Ack.FromString,
                _registered_method=True)
        self.GetRoomParticipants = channel.unary_unary(
                '/kasugai.RoomService/GetRoomParticipants',
                request_serializer=kasugai__pb2.Id.SerializeToString,
                response_deserializer=kasugai__pb2.RoomParticipants.FromString,
                _registered_method=True)


class RoomServiceServicer(object):
    """Missing associated documentation comment in .proto file."""

    def CreateRoom(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')

    def JoinRoom(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')

    def LeaveRoom(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')

    def GetRoomParticipants(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')


def add_RoomServiceServicer_to_server(servicer, server):
    rpc_method_handlers = {
            'CreateRoom': grpc.unary_unary_rpc_method_handler(
                    servicer.CreateRoom,
                    request_deserializer=kasugai__pb2.Room.FromString,
                    response_serializer=kasugai__pb2.Ack.SerializeToString,
            ),
            'JoinRoom': grpc.unary_unary_rpc_method_handler(
                    servicer.JoinRoom,
                    request_deserializer=kasugai__pb2.Id.FromString,
                    response_serializer=kasugai__pb2.Ack.SerializeToString,
            ),
            'LeaveRoom': grpc.unary_unary_rpc_method_handler(
                    servicer.LeaveRoom,
                    request_deserializer=kasugai__pb2.Id.FromString,
                    response_serializer=kasugai__pb2.Ack.SerializeToString,
            ),
            'GetRoomParticipants': grpc.unary_unary_rpc_method_handler(
                    servicer.GetRoomParticipants,
                    request_deserializer=kasugai__pb2.Id.FromString,
                    response_serializer=kasugai__pb2.RoomParticipants.SerializeToString,
            ),
    }
    generic_handler = grpc.method_handlers_generic_handler(
            'kasugai.RoomService', rpc_method_handlers)
    server.add_generic_rpc_handlers((generic_handler,))
    server.add_registered_method_handlers('kasugai.RoomService', rpc_method_handlers)


 # This class is part of an EXPERIMENTAL API.
class RoomService(object):
    """Missing associated documentation comment in .proto file."""

    @staticmethod
    def CreateRoom(request,
            target,
            options=(),
            channel_credentials=None,
            call_credentials=None,
            insecure=False,
            compression=None,
            wait_for_ready=None,
            timeout=None,
            metadata=None):
        return grpc.experimental.unary_unary(
            request,
            target,
            '/kasugai.RoomService/CreateRoom',
            kasugai__pb2.Room.SerializeToString,
            kasugai__pb2.Ack.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True)

    @staticmethod
    def JoinRoom(request,
            target,
            options=(),
            channel_credentials=None,
            call_credentials=None,
            insecure=False,
            compression=None,
            wait_for_ready=None,
            timeout=None,
            metadata=None):
        return grpc.experimental.unary_unary(
            request,
            target,
            '/kasugai.RoomService/JoinRoom',
            kasugai__pb2.Id.SerializeToString,
            kasugai__pb2.Ack.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True)

    @staticmethod
    def LeaveRoom(request,
            target,
            options=(),
            channel_credentials=None,
            call_credentials=None,
            insecure=False,
            compression=None,
            wait_for_ready=None,
            timeout=None,
            metadata=None):
        return grpc.experimental.unary_unary(
            request,
            target,
            '/kasugai.RoomService/LeaveRoom',
            kasugai__pb2.Id.SerializeToString,
            kasugai__pb2.Ack.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True)

    @staticmethod
    def GetRoomParticipants(request,
            target,
            options=(),
            channel_credentials=None,
            call_credentials=None,
            insecure=False,
            compression=None,
            wait_for_ready=None,
            timeout=None,
            metadata=None):
        return grpc.experimental.unary_unary(
            request,
            target,
            '/kasugai.RoomService/GetRoomParticipants',
            kasugai__pb2.Id.SerializeToString,
            kasugai__pb2.RoomParticipants.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True)


class ChatServiceStub(object):
    """Missing associated documentation comment in .proto file."""

    def __init__(self, channel):
        """Constructor.

        Args:
            channel: A grpc.Channel.
        """
        self.SendTextMessage = channel.unary_unary(
                '/kasugai.ChatService/SendTextMessage',
                request_serializer=kasugai__pb2.TextMessage.SerializeToString,
                response_deserializer=kasugai__pb2.Ack.FromString,
                _registered_method=True)
        self.ReceiveTextMessages = channel.unary_stream(
                '/kasugai.ChatService/ReceiveTextMessages',
                request_serializer=kasugai__pb2.Id.SerializeToString,
                response_deserializer=kasugai__pb2.TextMessage.FromString,
                _registered_method=True)


class ChatServiceServicer(object):
    """Missing associated documentation comment in .proto file."""

    def SendTextMessage(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')

    def ReceiveTextMessages(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')


def add_ChatServiceServicer_to_server(servicer, server):
    rpc_method_handlers = {
            'SendTextMessage': grpc.unary_unary_rpc_method_handler(
                    servicer.SendTextMessage,
                    request_deserializer=kasugai__pb2.TextMessage.FromString,
                    response_serializer=kasugai__pb2.Ack.SerializeToString,
            ),
            'ReceiveTextMessages': grpc.unary_stream_rpc_method_handler(
                    servicer.ReceiveTextMessages,
                    request_deserializer=kasugai__pb2.Id.FromString,
                    response_serializer=kasugai__pb2.TextMessage.SerializeToString,
            ),
    }
    generic_handler = grpc.method_handlers_generic_handler(
            'kasugai.ChatService', rpc_method_handlers)
    server.add_generic_rpc_handlers((generic_handler,))
    server.add_registered_method_handlers('kasugai.ChatService', rpc_method_handlers)


 # This class is part of an EXPERIMENTAL API.
class ChatService(object):
    """Missing associated documentation comment in .proto file."""

    @staticmethod
    def SendTextMessage(request,
            target,
            options=(),
            channel_credentials=None,
            call_credentials=None,
            insecure=False,
            compression=None,
            wait_for_ready=None,
            timeout=None,
            metadata=None):
        return grpc.experimental.unary_unary(
            request,
            target,
            '/kasugai.ChatService/SendTextMessage',
            kasugai__pb2.TextMessage.SerializeToString,
            kasugai__pb2.Ack.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True)

    @staticmethod
    def ReceiveTextMessages(request,
            target,
            options=(),
            channel_credentials=None,
            call_credentials=None,
            insecure=False,
            compression=None,
            wait_for_ready=None,
            timeout=None,
            metadata=None):
        return grpc.experimental.unary_stream(
            request,
            target,
            '/kasugai.ChatService/ReceiveTextMessages',
            kasugai__pb2.Id.SerializeToString,
            kasugai__pb2.TextMessage.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True)


class MediaServiceStub(object):
    """Missing associated documentation comment in .proto file."""

    def __init__(self, channel):
        """Constructor.

        Args:
            channel: A grpc.Channel.
        """
        self.StartMediaStream = channel.stream_stream(
                '/kasugai.MediaService/StartMediaStream',
                request_serializer=kasugai__pb2.MediaStream.SerializeToString,
                response_deserializer=kasugai__pb2.MediaStream.FromString,
                _registered_method=True)
        self.EndMediaStream = channel.unary_unary(
                '/kasugai.MediaService/EndMediaStream',
                request_serializer=kasugai__pb2.Id.SerializeToString,
                response_deserializer=kasugai__pb2.Ack.FromString,
                _registered_method=True)
        self.ManageVoIPCall = channel.stream_stream(
                '/kasugai.MediaService/ManageVoIPCall',
                request_serializer=kasugai__pb2.VoIPSignal.SerializeToString,
                response_deserializer=kasugai__pb2.VoIPSignal.FromString,
                _registered_method=True)


class MediaServiceServicer(object):
    """Missing associated documentation comment in .proto file."""

    def StartMediaStream(self, request_iterator, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')

    def EndMediaStream(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')

    def ManageVoIPCall(self, request_iterator, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')


def add_MediaServiceServicer_to_server(servicer, server):
    rpc_method_handlers = {
            'StartMediaStream': grpc.stream_stream_rpc_method_handler(
                    servicer.StartMediaStream,
                    request_deserializer=kasugai__pb2.MediaStream.FromString,
                    response_serializer=kasugai__pb2.MediaStream.SerializeToString,
            ),
            'EndMediaStream': grpc.unary_unary_rpc_method_handler(
                    servicer.EndMediaStream,
                    request_deserializer=kasugai__pb2.Id.FromString,
                    response_serializer=kasugai__pb2.Ack.SerializeToString,
            ),
            'ManageVoIPCall': grpc.stream_stream_rpc_method_handler(
                    servicer.ManageVoIPCall,
                    request_deserializer=kasugai__pb2.VoIPSignal.FromString,
                    response_serializer=kasugai__pb2.VoIPSignal.SerializeToString,
            ),
    }
    generic_handler = grpc.method_handlers_generic_handler(
            'kasugai.MediaService', rpc_method_handlers)
    server.add_generic_rpc_handlers((generic_handler,))
    server.add_registered_method_handlers('kasugai.MediaService', rpc_method_handlers)


 # This class is part of an EXPERIMENTAL API.
class MediaService(object):
    """Missing associated documentation comment in .proto file."""

    @staticmethod
    def StartMediaStream(request_iterator,
            target,
            options=(),
            channel_credentials=None,
            call_credentials=None,
            insecure=False,
            compression=None,
            wait_for_ready=None,
            timeout=None,
            metadata=None):
        return grpc.experimental.stream_stream(
            request_iterator,
            target,
            '/kasugai.MediaService/StartMediaStream',
            kasugai__pb2.MediaStream.SerializeToString,
            kasugai__pb2.MediaStream.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True)

    @staticmethod
    def EndMediaStream(request,
            target,
            options=(),
            channel_credentials=None,
            call_credentials=None,
            insecure=False,
            compression=None,
            wait_for_ready=None,
            timeout=None,
            metadata=None):
        return grpc.experimental.unary_unary(
            request,
            target,
            '/kasugai.MediaService/EndMediaStream',
            kasugai__pb2.Id.SerializeToString,
            kasugai__pb2.Ack.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True)

    @staticmethod
    def ManageVoIPCall(request_iterator,
            target,
            options=(),
            channel_credentials=None,
            call_credentials=None,
            insecure=False,
            compression=None,
            wait_for_ready=None,
            timeout=None,
            metadata=None):
        return grpc.experimental.stream_stream(
            request_iterator,
            target,
            '/kasugai.MediaService/ManageVoIPCall',
            kasugai__pb2.VoIPSignal.SerializeToString,
            kasugai__pb2.VoIPSignal.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True)


class FileTransferServiceStub(object):
    """Missing associated documentation comment in .proto file."""

    def __init__(self, channel):
        """Constructor.

        Args:
            channel: A grpc.Channel.
        """
        self.InitiateFileTransfer = channel.unary_unary(
                '/kasugai.FileTransferService/InitiateFileTransfer',
                request_serializer=kasugai__pb2.FileMetadata.SerializeToString,
                response_deserializer=kasugai__pb2.Ack.FromString,
                _registered_method=True)
        self.TransferFileChunk = channel.stream_unary(
                '/kasugai.FileTransferService/TransferFileChunk',
                request_serializer=kasugai__pb2.FileChunk.SerializeToString,
                response_deserializer=kasugai__pb2.Ack.FromString,
                _registered_method=True)
        self.ReceiveFileMetadata = channel.unary_unary(
                '/kasugai.FileTransferService/ReceiveFileMetadata',
                request_serializer=kasugai__pb2.Id.SerializeToString,
                response_deserializer=kasugai__pb2.FileMetadata.FromString,
                _registered_method=True)
        self.ReceiveFileChunks = channel.unary_stream(
                '/kasugai.FileTransferService/ReceiveFileChunks',
                request_serializer=kasugai__pb2.Id.SerializeToString,
                response_deserializer=kasugai__pb2.FileChunk.FromString,
                _registered_method=True)


class FileTransferServiceServicer(object):
    """Missing associated documentation comment in .proto file."""

    def InitiateFileTransfer(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')

    def TransferFileChunk(self, request_iterator, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')

    def ReceiveFileMetadata(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')

    def ReceiveFileChunks(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')


def add_FileTransferServiceServicer_to_server(servicer, server):
    rpc_method_handlers = {
            'InitiateFileTransfer': grpc.unary_unary_rpc_method_handler(
                    servicer.InitiateFileTransfer,
                    request_deserializer=kasugai__pb2.FileMetadata.FromString,
                    response_serializer=kasugai__pb2.Ack.SerializeToString,
            ),
            'TransferFileChunk': grpc.stream_unary_rpc_method_handler(
                    servicer.TransferFileChunk,
                    request_deserializer=kasugai__pb2.FileChunk.FromString,
                    response_serializer=kasugai__pb2.Ack.SerializeToString,
            ),
            'ReceiveFileMetadata': grpc.unary_unary_rpc_method_handler(
                    servicer.ReceiveFileMetadata,
                    request_deserializer=kasugai__pb2.Id.FromString,
                    response_serializer=kasugai__pb2.FileMetadata.SerializeToString,
            ),
            'ReceiveFileChunks': grpc.unary_stream_rpc_method_handler(
                    servicer.ReceiveFileChunks,
                    request_deserializer=kasugai__pb2.Id.FromString,
                    response_serializer=kasugai__pb2.FileChunk.SerializeToString,
            ),
    }
    generic_handler = grpc.method_handlers_generic_handler(
            'kasugai.FileTransferService', rpc_method_handlers)
    server.add_generic_rpc_handlers((generic_handler,))
    server.add_registered_method_handlers('kasugai.FileTransferService', rpc_method_handlers)


 # This class is part of an EXPERIMENTAL API.
class FileTransferService(object):
    """Missing associated documentation comment in .proto file."""

    @staticmethod
    def InitiateFileTransfer(request,
            target,
            options=(),
            channel_credentials=None,
            call_credentials=None,
            insecure=False,
            compression=None,
            wait_for_ready=None,
            timeout=None,
            metadata=None):
        return grpc.experimental.unary_unary(
            request,
            target,
            '/kasugai.FileTransferService/InitiateFileTransfer',
            kasugai__pb2.FileMetadata.SerializeToString,
            kasugai__pb2.Ack.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True)

    @staticmethod
    def TransferFileChunk(request_iterator,
            target,
            options=(),
            channel_credentials=None,
            call_credentials=None,
            insecure=False,
            compression=None,
            wait_for_ready=None,
            timeout=None,
            metadata=None):
        return grpc.experimental.stream_unary(
            request_iterator,
            target,
            '/kasugai.FileTransferService/TransferFileChunk',
            kasugai__pb2.FileChunk.SerializeToString,
            kasugai__pb2.Ack.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True)

    @staticmethod
    def ReceiveFileMetadata(request,
            target,
            options=(),
            channel_credentials=None,
            call_credentials=None,
            insecure=False,
            compression=None,
            wait_for_ready=None,
            timeout=None,
            metadata=None):
        return grpc.experimental.unary_unary(
            request,
            target,
            '/kasugai.FileTransferService/ReceiveFileMetadata',
            kasugai__pb2.Id.SerializeToString,
            kasugai__pb2.FileMetadata.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True)

    @staticmethod
    def ReceiveFileChunks(request,
            target,
            options=(),
            channel_credentials=None,
            call_credentials=None,
            insecure=False,
            compression=None,
            wait_for_ready=None,
            timeout=None,
            metadata=None):
        return grpc.experimental.unary_stream(
            request,
            target,
            '/kasugai.FileTransferService/ReceiveFileChunks',
            kasugai__pb2.Id.SerializeToString,
            kasugai__pb2.FileChunk.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True)
