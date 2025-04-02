import grpc
from server_logger import ServerLogger 

class AuthInterceptor(grpc.ServerInterceptor):
    def __init__(self, valid_token):
        self.valid_token = valid_token
        self.logger = ServerLogger.get_logger("AuthInterceptor")

    def intercept_service(self, continuation, handler_call_details):
        # Extract metadata as a dictionary
        metadata = dict(handler_call_details.invocation_metadata or [])
        token = metadata.get('authorization')
        if token != self.valid_token:
            self.logger.error("Authentication failed: Invalid or missing token.")
            # Define an abort handler that will be used for this call.
            def abort_handler(request, context):
                context.abort(grpc.StatusCode.UNAUTHENTICATED, "Invalid authorization token")
            # Depending on the RPC method type, you may need to handle multiple handlers.
            # Here, we assume unary-unary methods for simplicity.
            return grpc.unary_unary_rpc_method_handler(abort_handler)
        self.logger.info("Authentication successful for incoming call.")
        return continuation(handler_call_details)
