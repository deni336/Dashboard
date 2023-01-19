# Generated by the gRPC Python protocol compiler plugin. DO NOT EDIT!
"""Client and server classes corresponding to protobuf-defined services."""
import grpc

import kasugai_pb2 as kasugai__pb2


class BroadcastStub(object):
    """Missing associated documentation comment in .proto file."""

    def __init__(self, channel):
        """Constructor.

        Args:
            channel: A grpc.Channel.
        """
        self.ChatService = channel.stream_stream(
                '/kasugai.Broadcast/ChatService',
                request_serializer=kasugai__pb2.MessageResponse.SerializeToString,
                response_deserializer=kasugai__pb2.MessageResponse.FromString,
                )
        self.ActiveUsers = channel.unary_unary(
                '/kasugai.Broadcast/ActiveUsers',
                request_serializer=kasugai__pb2.ActiveUsersRequest.SerializeToString,
                response_deserializer=kasugai__pb2.ActiveUsersList.FromString,
                )


class BroadcastServicer(object):
    """Missing associated documentation comment in .proto file."""

    def ChatService(self, request_iterator, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')

    def ActiveUsers(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')


def add_BroadcastServicer_to_server(servicer, server):
    rpc_method_handlers = {
            'ChatService': grpc.stream_stream_rpc_method_handler(
                    servicer.ChatService,
                    request_deserializer=kasugai__pb2.MessageResponse.FromString,
                    response_serializer=kasugai__pb2.MessageResponse.SerializeToString,
            ),
            'ActiveUsers': grpc.unary_unary_rpc_method_handler(
                    servicer.ActiveUsers,
                    request_deserializer=kasugai__pb2.ActiveUsersRequest.FromString,
                    response_serializer=kasugai__pb2.ActiveUsersList.SerializeToString,
            ),
    }
    generic_handler = grpc.method_handlers_generic_handler(
            'kasugai.Broadcast', rpc_method_handlers)
    server.add_generic_rpc_handlers((generic_handler,))


 # This class is part of an EXPERIMENTAL API.
class Broadcast(object):
    """Missing associated documentation comment in .proto file."""

    @staticmethod
    def ChatService(request_iterator,
            target,
            options=(),
            channel_credentials=None,
            call_credentials=None,
            insecure=False,
            compression=None,
            wait_for_ready=None,
            timeout=None,
            metadata=None):
        return grpc.experimental.stream_stream(request_iterator, target, '/kasugai.Broadcast/ChatService',
            kasugai__pb2.MessageResponse.SerializeToString,
            kasugai__pb2.MessageResponse.FromString,
            options, channel_credentials,
            insecure, call_credentials, compression, wait_for_ready, timeout, metadata)

    @staticmethod
    def ActiveUsers(request,
            target,
            options=(),
            channel_credentials=None,
            call_credentials=None,
            insecure=False,
            compression=None,
            wait_for_ready=None,
            timeout=None,
            metadata=None):
        return grpc.experimental.unary_unary(request, target, '/kasugai.Broadcast/ActiveUsers',
            kasugai__pb2.ActiveUsersRequest.SerializeToString,
            kasugai__pb2.ActiveUsersList.FromString,
            options, channel_credentials,
            insecure, call_credentials, compression, wait_for_ready, timeout, metadata)